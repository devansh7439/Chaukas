"""From audio chunks to transcribed lines: the per-stream processor and the threaded pipeline."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("onnxruntime")

from chaukas.asr.base import Transcript  # noqa: E402
from chaukas.audio.pipeline import AudioPipeline, StreamProcessor  # noqa: E402
from chaukas.audio.vad import SileroVad, find_vad_model  # noqa: E402
from chaukas.core.config import load_config  # noqa: E402
from chaukas.core.models import HeardLine, Stream  # noqa: E402

AUDIO = load_config().audio
RATE = 16_000


@pytest.fixture(scope="module")
def vad_model() -> object:
    path = find_vad_model()
    if path is None:
        pytest.skip("no Silero VAD model available")
    return path


def trimmed(samples: object) -> object:
    """Synthetic speech without the silence the synthesiser adds around it."""
    loud = np.flatnonzero(np.abs(samples) > 0.01)  # type: ignore[arg-type]
    return samples[loud[0] : loud[-1] + 1]  # type: ignore[index]


def processor(vad_model: object, stream: Stream = Stream.CALLER) -> StreamProcessor:
    return StreamProcessor(stream, SileroVad(vad_model), AUDIO, in_rate=RATE, channels=1)  # type: ignore[arg-type]


def chunks(samples: object, seconds: float = 0.1) -> list[object]:
    size = int(RATE * seconds)
    return [samples[i : i + size] for i in range(0, len(samples), size)]  # type: ignore[index]


def play(proc: StreamProcessor, samples: object, start: float) -> list[object]:
    """Feed audio as a device would: chunks arriving in real time from ``start``."""
    segments = []
    t = start
    for chunk in chunks(samples):
        t += len(chunk) / RATE  # type: ignore[arg-type]
        segments.extend(proc.process(chunk, arrived=t))
    return segments


class TestStreamProcessor:
    def test_a_spoken_sentence_becomes_one_segment_on_the_session_clock(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        sentence = speech("Please tell me the OTP you just received.")
        silence = np.zeros(RATE, dtype=np.float32)
        audio = np.concatenate([silence, sentence, silence])
        (segment,) = play(processor(vad_model), audio, start=50.0)
        assert segment.stream is Stream.CALLER
        assert 50.5 < segment.t_start < 51.2  # the sentence starts 1 s in
        spoken = len(sentence) / RATE  # type: ignore[arg-type]
        assert segment.duration == pytest.approx(spoken, abs=0.8)

    def test_a_gap_in_the_audio_closes_speech_and_keeps_time_right(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        proc = processor(vad_model)
        sentence = trimmed(speech("Stay on camera and do not disconnect."))
        first = play(proc, sentence, start=10.0)
        # nothing arrives for 20 s (loopback sends no data while nothing plays)
        end_of_first = 10.0 + len(sentence) / RATE  # type: ignore[arg-type]
        later = play(proc, np.concatenate([sentence, np.zeros(RATE, dtype=np.float32)]),
                     start=end_of_first + 20.0)  # fmt: skip
        segments = first + later
        assert len(segments) == 2
        assert segments[1].t_start == pytest.approx(end_of_first + 20.0, abs=0.5)

    def test_a_burst_of_backlog_does_not_push_the_stream_clock_ahead(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        """After the PC wakes from sleep, capture hands over the gap as silence all at once.

        Those chunks all arrive at about the same moment; counting them as audio would put
        the stream clock (and every later line) up to a minute ahead of the session clock.
        """
        proc = processor(vad_model)
        play(proc, np.zeros(RATE, dtype=np.float32), start=0.0)  # 1 s of normal audio
        for _ in range(100):  # 10 s of silence, delivered in one burst at t = 1.05
            proc.process(np.zeros(RATE // 10, dtype=np.float32), arrived=1.05)
        sentence = trimmed(speech("Tell me the code."))
        audio = np.concatenate([sentence, np.zeros(RATE, dtype=np.float32)])
        (segment,) = play(proc, audio, start=1.05)
        assert segment.t_start == pytest.approx(1.05, abs=0.5)

    def test_idle_closes_speech_when_audio_stops_arriving(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        proc = processor(vad_model)
        sentence = trimmed(speech("Transfer the amount now."))
        assert play(proc, sentence, start=0.0) == []  # still "speaking" at the end
        end = len(sentence) / RATE  # type: ignore[arg-type]
        assert proc.idle(now=end + 0.2) == []
        assert len(proc.idle(now=end + 1.0)) == 1

    def test_stereo_48k_devices_are_converted(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        sentence = speech("Install AnyDesk so I can help you.")
        stereo_48k = np.repeat(np.repeat(sentence, 3), 2)  # crude 48 kHz stereo
        proc = StreamProcessor(Stream.CALLER, SileroVad(vad_model), AUDIO, in_rate=48_000,  # type: ignore[arg-type]
                               channels=2)  # fmt: skip
        size = 4800 * 2
        t = 0.0
        segments = []
        for i in range(0, len(stereo_48k), size):
            t += 0.1
            segments.extend(proc.process(stereo_48k[i : i + size], arrived=t))
        segments.extend(proc.idle(now=t + 1.0))
        assert len(segments) == 1


class ScriptedTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def transcribe(self, samples: object, *, language: str | None = None) -> Transcript:
        self.calls += 1
        return Transcript(text=self.text, language="en", ms=5.0)


class TestAudioPipeline:
    def test_lines_come_out_transcribed_and_tagged_with_their_stream(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        heard: list[HeardLine] = []
        done = threading.Event()

        def on_line(line: HeardLine) -> None:
            heard.append(line)
            done.set()

        pipeline = AudioPipeline(
            AUDIO, vad_model=vad_model, transcriber=ScriptedTranscriber("OTP batao"),  # type: ignore[arg-type]
            on_line=on_line,
        )  # fmt: skip
        pipeline.add_stream(Stream.CALLER, in_rate=RATE, channels=1)
        pipeline.start()
        try:
            audio = np.concatenate([speech("Tell me the OTP."), np.zeros(RATE, np.float32)])
            t = 5.0
            for chunk in chunks(audio):
                t += 0.1
                pipeline.feed(Stream.CALLER, chunk, arrived=t)
            assert done.wait(10.0)
        finally:
            pipeline.stop()
        (line,) = heard
        assert line.stream is Stream.CALLER
        assert line.text == "OTP batao"
        assert 5.0 <= line.t_start < line.t_end <= t

    def test_the_callers_voice_leaking_into_the_microphone_is_dropped(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        heard: list[HeardLine] = []
        pipeline = AudioPipeline(
            AUDIO, vad_model=vad_model,  # type: ignore[arg-type]
            transcriber=ScriptedTranscriber("aapke naam pe arrest warrant hai"),
            on_line=heard.append,
        )  # fmt: skip
        pipeline.add_stream(Stream.CALLER, in_rate=RATE, channels=1)
        pipeline.add_stream(Stream.USER, in_rate=RATE, channels=1)
        pipeline.start()
        try:
            audio = np.concatenate([speech("Arrest warrant."), np.zeros(RATE, np.float32)])
            t = 0.0
            for chunk in chunks(audio):
                t += 0.1
                pipeline.feed(Stream.CALLER, chunk, arrived=t)
                pipeline.feed(Stream.USER, chunk, arrived=t)  # the mic hears the speaker
            pipeline.drain(10.0)
        finally:
            pipeline.stop()
        assert [line.stream for line in heard] == [Stream.CALLER]

    def test_blank_transcripts_are_not_lines(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        heard: list[HeardLine] = []
        pipeline = AudioPipeline(
            AUDIO,
            vad_model=vad_model,  # type: ignore[arg-type]
            transcriber=ScriptedTranscriber(""),
            on_line=heard.append,
        )
        pipeline.add_stream(Stream.USER, in_rate=RATE, channels=1)
        pipeline.start()
        try:
            audio = np.concatenate([speech("Hmm."), np.zeros(RATE, np.float32)])
            for i, chunk in enumerate(chunks(audio)):
                pipeline.feed(Stream.USER, chunk, arrived=0.1 * (i + 1))
            pipeline.drain(10.0)
        finally:
            pipeline.stop()
        assert heard == []


class RecordingTranscriber:
    """Records each call's audio length and language hint; can be slow, like Whisper."""

    def __init__(self, delay_s: float = 0.0, language: str = "hi") -> None:
        self.delay_s = delay_s
        self.language = language
        self.calls: list[tuple[float, str | None]] = []

    def transcribe(self, samples: object, *, language: str | None = None) -> Transcript:
        self.calls.append((len(samples) / RATE, language))  # type: ignore[arg-type]
        time.sleep(self.delay_s)
        return Transcript(text=f"line {len(self.calls)}", language=self.language, ms=1.0)


def run_sentences(
    vad_model: object,
    speech: Callable[[str], object],
    transcriber: RecordingTranscriber,
    count: int,
    merge_max_s: float = 20.0,
) -> list[HeardLine]:
    heard: list[HeardLine] = []
    config = AUDIO
    pipeline = AudioPipeline(config, vad_model=vad_model,  # type: ignore[arg-type]
                             transcriber=transcriber, on_line=heard.append,
                             redetect_every=3, merge_max_s=merge_max_s)  # fmt: skip
    pipeline.add_stream(Stream.CALLER, in_rate=RATE, channels=1)
    pipeline.start()
    try:
        sentence = trimmed(speech("Please tell me the code."))
        pause = np.zeros(int(RATE * 0.9), dtype=np.float32)
        audio = np.concatenate([part for _ in range(count) for part in (sentence, pause)])
        t = 0.0
        for chunk in chunks(audio):
            t += 0.1
            pipeline.feed(Stream.CALLER, chunk, arrived=t)
        assert pipeline.drain(30.0)
    finally:
        pipeline.stop()
    return heard


class TestSpeed:
    def test_language_is_detected_once_then_reused_and_rechecked(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        transcriber = RecordingTranscriber()
        run_sentences(vad_model, speech, transcriber, count=5, merge_max_s=0.0)  # no merging
        hints = [language for _, language in transcriber.calls]
        assert len(hints) == 5
        assert hints == [None, "hi", "hi", "hi", None]  # detect, reuse 3 times, detect again

    def test_a_backlog_is_transcribed_in_one_call(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        transcriber = RecordingTranscriber(delay_s=1.5)  # slower than the speech arrives
        heard = run_sentences(vad_model, speech, transcriber, count=4)
        assert len(transcriber.calls) < 4  # some sentences were merged
        assert sum(seconds for seconds, _ in transcriber.calls) > 3.0  # nothing was lost
        assert heard[0].t_start < heard[-1].t_start


class TestEchoSkipping:
    """The mic's copy of the caller (laptop speakers) is skipped before Whisper runs."""

    def run_both(self, vad_model: object, speech: Callable[[str], object], user_delay_s: float,
                 transcriber: ScriptedTranscriber) -> list[HeardLine]:  # fmt: skip
        heard: list[HeardLine] = []
        pipeline = AudioPipeline(AUDIO, vad_model=vad_model,  # type: ignore[arg-type]
                                 transcriber=transcriber, on_line=heard.append)  # fmt: skip
        pipeline.add_stream(Stream.CALLER, in_rate=RATE, channels=1)
        pipeline.add_stream(Stream.USER, in_rate=RATE, channels=1)
        pipeline.start()
        try:
            sentence = trimmed(speech("Tell me the code now."))
            silence = np.zeros(int(RATE * (user_delay_s + 2.0)), dtype=np.float32)
            caller = np.concatenate([sentence, silence])
            delay = np.zeros(int(RATE * user_delay_s), dtype=np.float32)
            user = np.concatenate([delay, sentence, np.zeros(RATE * 2, dtype=np.float32)])
            t = 0.0
            for c_chunk, u_chunk in zip(chunks(caller), chunks(user), strict=False):
                t += 0.1
                pipeline.feed(Stream.CALLER, c_chunk, arrived=t)
                pipeline.feed(Stream.USER, u_chunk, arrived=t)
            assert pipeline.drain(20.0)
        finally:
            pipeline.stop()
        return heard

    def test_speech_inside_the_callers_speech_is_not_transcribed(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        transcriber = ScriptedTranscriber("tell me the code now")
        heard = self.run_both(vad_model, speech, user_delay_s=0.0, transcriber=transcriber)
        assert transcriber.calls == 1  # the caller only; the echo never reached Whisper
        assert [line.stream for line in heard] == [Stream.CALLER]

    def test_the_users_own_turn_after_the_caller_is_transcribed(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        transcriber = ScriptedTranscriber("four five six seven")
        heard = self.run_both(vad_model, speech, user_delay_s=3.0, transcriber=transcriber)
        assert transcriber.calls == 2
        assert [line.stream for line in heard] == [Stream.CALLER, Stream.USER]


class TestTurnOrder:
    def test_the_user_waits_for_caller_speech_that_began_before_they_stopped(
        self, vad_model: object, speech: Callable[[str], object]
    ) -> None:
        """The caller starts talking just before the user stops and goes on for seconds.

        The user's segment closes while the caller is still mid-sentence. It must wait for
        that sentence (which overlaps it) rather than go to Whisper first.
        """
        heard: list[HeardLine] = []
        pipeline = AudioPipeline(AUDIO, vad_model=vad_model,  # type: ignore[arg-type]
                                 transcriber=RecordingTranscriber(),
                                 on_line=heard.append)  # fmt: skip
        pipeline.add_stream(Stream.CALLER, in_rate=RATE, channels=1)
        pipeline.add_stream(Stream.USER, in_rate=RATE, channels=1)
        pipeline.start()
        try:
            said = trimmed(speech("Four five six seven."))
            long = trimmed(speech("Stay on the line and do not disconnect this call, "
                                  "whatever happens, until the officer joins you."))  # fmt: skip
            lead = np.zeros(int(RATE * 0.5), dtype=np.float32)
            overlap = int(RATE * 0.3)
            caller_start = len(lead) + len(said) - overlap  # type: ignore[arg-type]
            tail = np.zeros(RATE * 2, dtype=np.float32)
            user = np.concatenate([lead, said, np.zeros(len(long) + RATE * 2, np.float32)])  # type: ignore[arg-type]
            caller = np.concatenate([np.zeros(caller_start, np.float32), long, tail])
            t = 0.0
            for c_chunk, u_chunk in zip(chunks(caller), chunks(user), strict=False):
                t += 0.1
                pipeline.feed(Stream.CALLER, c_chunk, arrived=t)
                pipeline.feed(Stream.USER, u_chunk, arrived=t)
                time.sleep(0.03)  # about 3x real time: the caller is mid-sentence for a while
            assert pipeline.drain(20.0)
        finally:
            pipeline.stop()
        assert [line.stream for line in heard] == [Stream.CALLER, Stream.USER]
