"""From audio chunks to transcribed lines, for both sides of a call.

    capture callback --feed()--> [stream worker: resample -> VAD -> segment] --+
    capture callback --feed()--> [stream worker: resample -> VAD -> segment] --+--> [ASR worker]
                                                                                    |
                                                          on_line(HeardLine) <------+

* One worker thread per stream keeps the capture callbacks tiny (they only enqueue).
* One ASR worker transcribes segments in order, so CPU use stays bounded.
* The user's lines wait briefly until the caller's audio up to the same moment has been
  transcribed, so the echo guard can recognise the caller's voice leaking into the mic.
* Mic speech that lies almost entirely inside the caller's speech (``echo_overlap_skip``)
  is the speakers' echo on a PC without headphones; it is dropped before Whisper runs,
  which halves the transcription load in that setup.
* Whisper pays a fixed cost per call (it always processes a 30 s window) and language
  detection doubles it. So each speaker's language is detected once and reused (re-checked
  every ``redetect_every`` lines), and when the worker falls behind, a speaker's queued
  segments are transcribed together in one call (up to ``merge_max_s`` of audio).

Times are on the session clock: ``arrived`` is when a chunk reached us, so a chunk covers
``[arrived - its duration, arrived]``.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import numpy as np

from chaukas.asr.base import Transcriber
from chaukas.audio.convert import TARGET_RATE, Samples, StreamResampler
from chaukas.audio.guards import EchoGuard, PlaybackGuard
from chaukas.audio.segmenter import AudioSegment, Segmenter
from chaukas.audio.vad import WINDOW, SileroVad
from chaukas.core.config import AudioConfig
from chaukas.core.models import HeardLine, Stream

logger = logging.getLogger(__name__)

# Safety net only: a user line normally waits until the caller's audio up to the same
# moment is processed (stream time, so a busy machine can't release it early).
_ECHO_HOLD_S: Final = 30.0
_MERGE_GAP_S: Final = 0.25  # silence placed between merged segments
_CALLER_SPAN_MEMORY_S: Final = 120.0
_POLL_S: Final = 0.05
_QUEUE_CHUNKS: Final = 600  # about a minute of 100 ms chunks per stream
_MAX_LEAD_S: Final = 0.2  # stream clock ahead of arrivals by more: drop digital silence


class StreamProcessor:
    """One stream: device audio in, closed speech segments out. Not thread-safe."""

    __slots__ = ("_channels", "_config", "_guard", "_in_rate", "_last_arrival", "_resampler",
                 "_segmenter", "_stream", "_vad")  # fmt: skip

    def __init__(
        self,
        stream: Stream,
        vad: SileroVad,
        config: AudioConfig,
        *,
        in_rate: int,
        channels: int,
        guard: PlaybackGuard | None = None,
    ) -> None:
        self._stream = stream
        self._vad = vad
        self._config = config
        self._in_rate = in_rate
        self._channels = channels
        self._guard = guard
        self._resampler = StreamResampler(in_rate, channels)
        self._segmenter: Segmenter | None = None
        self._last_arrival: float | None = None

    @property
    def stream(self) -> Stream:
        return self._stream

    @property
    def now(self) -> float:
        """How far this stream's audio has been processed, on the session clock."""
        return self._segmenter.now if self._segmenter is not None else 0.0

    @property
    def in_speech(self) -> bool:
        return self._segmenter is not None and self._segmenter.in_speech

    @property
    def speech_start(self) -> float | None:
        """When the speech in progress began, on the session clock; None between segments."""
        return self._segmenter.speech_start if self._segmenter is not None else None

    def process(self, interleaved: Samples, *, arrived: float) -> list[AudioSegment]:
        closed: list[AudioSegment] = []
        start = arrived - len(interleaved) / self._channels / self._in_rate
        segmenter = self._segmenter
        if segmenter is None:
            segmenter = self._segmenter = self._new_segmenter(origin=start)
        elif start - segmenter.now > self._config.gap_reset_s:
            # Nothing arrived for a while (loopback is silent when nothing plays).
            gap_closed = segmenter.skip(start - segmenter.now)
            self._vad.reset()
            if gap_closed is not None:
                closed.append(gap_closed)
        elif (segmenter.now - start > _MAX_LEAD_S and not segmenter.in_speech
              and not np.any(interleaved)):  # fmt: skip
            # Digital silence while this stream is already ahead of the clock: a backlog
            # burst (after sleep the capture hands over the whole gap as zeros at once).
            # Counting it would push the stream clock, and every later line, ahead of the
            # session. Real audio is never exactly zero, so no speech is lost.
            self._last_arrival = arrived
            return closed
        for window, probability in self._vad.process(self._resampler.process(interleaved)):
            if self._guard is not None and self._guard.muted(segmenter.now):
                window, probability = np.zeros(WINDOW, dtype=np.float32), 0.0
            segment = segmenter.push(window, probability)
            if segment is not None:
                closed.append(segment)
        self._last_arrival = arrived
        return closed

    def idle(self, *, now: float) -> list[AudioSegment]:
        """No audio for a while: close speech in progress once silence would have."""
        segmenter = self._segmenter
        if segmenter is None or not segmenter.in_speech or self._last_arrival is None:
            return []
        if now - self._last_arrival < self._config.vad_silence_ms / 1000:
            return []
        segment = segmenter.flush()
        return [segment] if segment is not None else []

    def flush(self) -> list[AudioSegment]:
        if self._segmenter is None:
            return []
        segment = self._segmenter.flush()
        return [segment] if segment is not None else []

    def _new_segmenter(self, *, origin: float) -> Segmenter:
        config = self._config
        return Segmenter(
            self._stream,
            rate=TARGET_RATE,
            window=WINDOW,
            threshold=config.vad_threshold,
            silence_s=config.vad_silence_ms / 1000,
            max_s=config.max_segment_s,
            min_speech_s=config.min_speech_ms / 1000,
            pad_s=config.speech_pad_ms / 1000,
            origin=origin,
        )


class _LanguageMemory:
    """Each speaker's language: detect once, reuse it, re-check every ``every`` lines."""

    __slots__ = ("_every", "_known")

    def __init__(self, every: int) -> None:
        self._every = every
        self._known: dict[Stream, tuple[str, int]] = {}

    def hint(self, stream: Stream) -> str | None:
        known = self._known.get(stream)
        if known is None or known[1] >= self._every:
            return None
        return known[0]

    def learn(self, stream: Stream, language: str | None, *, hinted: bool) -> None:
        if hinted:
            known_language, uses = self._known[stream]
            self._known[stream] = (known_language, uses + 1)
        elif language:
            self._known[stream] = (language, 0)

    def reset(self) -> None:
        self._known.clear()


_FLUSH: Final = object()


@dataclass
class _StreamWorker:
    processor: StreamProcessor
    inbox: queue.Queue[tuple[Samples, float] | object] = field(
        default_factory=lambda: queue.Queue(maxsize=_QUEUE_CHUNKS)
    )
    thread: threading.Thread | None = None
    dropped: int = 0
    # Audio fully processed *and* its segments submitted, on the session clock. Published
    # only after submission, so the ASR worker never sees progress ahead of the queue.
    progress: float = 0.0
    # Start of the speech in progress at ``progress`` (None between segments). Published
    # just before ``progress``, so whoever reads ``progress`` first sees a start as new.
    speech_start: float | None = None


class AudioPipeline:
    def __init__(
        self,
        config: AudioConfig,
        *,
        vad_model: Path,
        transcriber: Transcriber,
        on_line: Callable[[HeardLine], None],
        clock: Callable[[], float] | None = None,
        playback_guard: PlaybackGuard | None = None,
        redetect_every: int = 6,
        merge_max_s: float = 20.0,
    ) -> None:
        self._config = config
        self._vad_model = vad_model
        self._transcriber = transcriber
        self._on_line = on_line
        self._clock = clock  # when given, speech in progress closes if audio stops arriving
        self._guard = playback_guard
        self._echo = EchoGuard(config.echo_similarity)
        self._languages = _LanguageMemory(redetect_every)
        self._merge_max_s = merge_max_s
        self._workers: dict[Stream, _StreamWorker] = {}
        self._segments: queue.Queue[AudioSegment] = queue.Queue()
        self._backlog: deque[AudioSegment] = deque()  # taken from the queue, not yet handled
        self._caller_spans: deque[tuple[float, float]] = deque()  # recent caller speech
        self._pending_caller: list[float] = []  # starts of caller segments not yet taken
        self._held: list[tuple[AudioSegment, float]] = []  # user segments waiting for the caller
        self._busy = 0  # segments queued or being transcribed
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._asr_thread: threading.Thread | None = None

    def add_stream(self, stream: Stream, *, in_rate: int, channels: int) -> None:
        if self._asr_thread is not None:
            raise RuntimeError("add streams before start()")
        guard = self._guard if stream is Stream.CALLER else None
        processor = StreamProcessor(stream, SileroVad(self._vad_model), self._config,
                                    in_rate=in_rate, channels=channels, guard=guard)  # fmt: skip
        self._workers[stream] = _StreamWorker(processor)

    def feed(self, stream: Stream, interleaved: Samples, *, arrived: float) -> None:
        """Called from the capture callback: must return at once."""
        worker = self._workers[stream]
        try:
            worker.inbox.put_nowait((interleaved, arrived))
        except queue.Full:
            worker.dropped += 1  # the machine can't keep up; drop rather than block audio

    def start(self) -> None:
        self._stop.clear()
        for stream, worker in self._workers.items():
            worker.thread = threading.Thread(
                target=self._run_stream,
                args=(worker,),
                name=f"chaukas-audio-{stream.value}",
                daemon=True,
            )
            worker.thread.start()
        self._asr_thread = threading.Thread(target=self._run_asr, name="chaukas-asr", daemon=True)
        self._asr_thread.start()

    def drain(self, timeout: float) -> bool:
        """Close speech in progress and wait until every segment is transcribed."""
        deadline = time.monotonic() + timeout
        for worker in self._workers.values():
            worker.inbox.put(_FLUSH)
        for worker in self._workers.values():
            while worker.inbox.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(_POLL_S)
        while time.monotonic() < deadline:
            with self._lock:
                if self._busy == 0 and not self._held:
                    return True
            time.sleep(_POLL_S)
        return False

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        threads = [w.thread for w in self._workers.values()] + [self._asr_thread]
        for thread in threads:
            if thread is not None:
                thread.join(timeout)
        self._asr_thread = None

    def reset(self) -> None:
        """Session end: forget the caller's recent words and the speakers' languages."""
        self._echo.reset()
        self._languages.reset()
        with self._lock:
            self._caller_spans.clear()

    # ---------------------------------------------------------------- workers

    def _run_stream(self, worker: _StreamWorker) -> None:
        while not self._stop.is_set():
            try:
                item = worker.inbox.get(timeout=_POLL_S)
            except queue.Empty:
                if self._clock is not None:
                    self._submit(worker.processor.idle(now=self._clock()))
                    worker.speech_start = worker.processor.speech_start
                continue
            try:
                if isinstance(item, tuple):
                    samples, arrived = item
                    self._submit(worker.processor.process(samples, arrived=arrived))
                else:  # _FLUSH
                    self._submit(worker.processor.flush())
            except Exception:
                stream = worker.processor.stream.value
                logger.exception("audio processing failed on the %s stream", stream)
            finally:
                worker.speech_start = worker.processor.speech_start
                worker.progress = worker.processor.now
                worker.inbox.task_done()

    def _submit(self, segments: list[AudioSegment]) -> None:
        for segment in segments:
            with self._lock:
                self._busy += 1
                if segment.stream is Stream.CALLER:
                    self._pending_caller.append(segment.t_start)
            self._segments.put(segment)

    def _run_asr(self) -> None:
        while not self._stop.is_set():
            if not self._backlog:
                try:
                    self._backlog.append(self._segments.get(timeout=_POLL_S))
                except queue.Empty:
                    self._release_held(force_after=_ECHO_HOLD_S)
                    continue
            while True:  # everything else already waiting, so a backlog can be merged
                try:
                    self._backlog.append(self._segments.get_nowait())
                except queue.Empty:
                    break
            batch = self._take_batch()
            if batch[0].stream is Stream.CALLER:
                self._remember_caller(batch)
            if batch[0].stream is Stream.USER and Stream.CALLER in self._workers:
                with self._lock:
                    now = time.monotonic()
                    self._held.extend((segment, now) for segment in batch)
                    self._busy -= len(batch)
            else:
                self._transcribe(batch)
                with self._lock:
                    self._busy -= len(batch)
            self._release_held(force_after=_ECHO_HOLD_S)

    def _take_batch(self) -> list[AudioSegment]:
        """The next segment, plus the same speaker's segments right behind it (merge)."""
        first = self._backlog.popleft()
        batch = [first]
        total = first.duration
        while self._backlog and self._backlog[0].stream is first.stream:
            following = self._backlog[0]
            if total + following.duration > self._merge_max_s:
                break
            batch.append(self._backlog.popleft())
            total += following.duration
        return batch

    def _release_held(self, *, force_after: float) -> None:
        """Transcribe held user segments once the caller's side can no longer surprise us."""
        with self._lock:
            ready = [
                (segment, since)
                for segment, since in self._held
                if self._caller_caught_up(segment) or time.monotonic() - since >= force_after
            ]
            for item in ready:
                self._held.remove(item)
        for segment, _ in sorted(ready, key=lambda item: item[0].t_end):
            if self._caller_coverage(segment) >= self._config.echo_overlap_skip:
                logger.debug("mic speech inside the caller's speech: echo, not transcribed")
                continue
            self._transcribe([segment])

    def _remember_caller(self, batch: list[AudioSegment]) -> None:
        with self._lock:
            for segment in batch:
                self._pending_caller.remove(segment.t_start)
            self._caller_spans.extend((s.t_start, s.t_end) for s in batch)
            horizon = batch[-1].t_end - _CALLER_SPAN_MEMORY_S
            while self._caller_spans and self._caller_spans[0][1] < horizon:
                self._caller_spans.popleft()

    def _caller_coverage(self, segment: AudioSegment) -> float:
        """Share of ``segment`` during which the caller was speaking."""
        if segment.duration <= 0:
            return 0.0
        with self._lock:
            spans = list(self._caller_spans)
        covered = sum(
            max(0.0, min(end, segment.t_end) - max(start, segment.t_start)) for start, end in spans
        )
        return min(1.0, covered / segment.duration)

    def _caller_caught_up(self, segment: AudioSegment) -> bool:
        """No caller speech that overlaps ``segment`` can still be on its way (hold the lock).

        A caller segment closes only after ``vad_silence_ms`` of silence, so processing
        merely past the user's end time is not enough. No caller segment that started
        before this one ended may still be waiting or still be in progress, and either the
        caller's audio has been processed past that end plus the silence window, or the
        caller stream is idle and not mid-sentence. All in stream time, so machine load
        cannot release a line early.
        """
        caller = self._workers.get(Stream.CALLER)
        if caller is None:
            return True
        progress = caller.progress  # first: the start read next is at least as new
        speech_start = caller.speech_start
        # last: a segment closed after the reads above is here (added before publishing)
        if any(start < segment.t_end for start in self._pending_caller):
            return False
        if speech_start is not None and speech_start < segment.t_end:
            return False  # the caller began speaking before the user stopped, still going
        silence_s = self._config.vad_silence_ms / 1000
        if progress >= segment.t_end + silence_s:
            return True
        return caller.inbox.unfinished_tasks == 0 and not caller.processor.in_speech

    def _transcribe(self, batch: list[AudioSegment]) -> None:
        """One Whisper call for one or more consecutive segments of the same speaker."""
        stream = batch[0].stream
        t_start, t_end = batch[0].t_start, batch[-1].t_end
        if len(batch) == 1:
            samples = batch[0].samples
        else:
            gap = np.zeros(int(TARGET_RATE * _MERGE_GAP_S), dtype=np.float32)
            parts: list[Samples] = []
            for segment in batch:
                parts.extend((segment.samples, gap))
            samples = np.concatenate(parts[:-1])
        hint = self._languages.hint(stream)
        try:
            transcript = self._transcriber.transcribe(samples, language=hint)
        except Exception:
            logger.exception("speech-to-text failed")
            return
        self._languages.learn(stream, transcript.language, hinted=hint is not None)
        text = transcript.text.strip()
        if not text:
            return
        if stream is Stream.CALLER:
            self._echo.caller_said(t_start, t_end, text)
        elif self._echo.is_echo(t_start, t_end, text):
            return
        line = HeardLine(
            stream=stream,
            t_start=t_start,
            t_end=t_end,
            text=text,
            language=transcript.language,
            asr_ms=transcript.ms,
        )
        try:
            self._on_line(line)
        except Exception:
            logger.exception("delivering a heard line failed")
