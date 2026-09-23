"""Cut one stream of audio into speech segments (blueprint 6.1).

Input is a sequence of fixed-size windows, each with a voice-activity probability. A
segment opens on the first speech window (with a little pre-roll so the first syllable is
kept) and closes after ``silence_s`` of silence (keeping a short tail), or is cut at
``max_s``. A forced cut happens at the quietest window of the last second, so words are not
split. Segments with less than ``min_speech_s`` of actual speech (clicks, coughs) are
dropped.

Times are seconds on the session clock: ``origin`` plus the windows seen so far, plus any
gaps reported with ``skip`` (WASAPI loopback delivers nothing while nothing is playing).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from chaukas.audio.convert import Samples
from chaukas.core.models import Stream


@dataclass(frozen=True, slots=True)
class AudioSegment:
    stream: Stream
    t_start: float
    t_end: float
    samples: Samples

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


class Segmenter:
    __slots__ = (
        "_buffer",
        "_energy",
        "_max_windows",
        "_min_speech_windows",
        "_offset",
        "_pad_windows",
        "_preroll",
        "_silence_run",
        "_silence_windows",
        "_speech_windows",
        "_start_index",
        "_stream",
        "_threshold",
        "_window_s",
        "_windows_seen",
    )

    def __init__(
        self,
        stream: Stream,
        *,
        rate: int,
        window: int,
        threshold: float,
        silence_s: float,
        max_s: float,
        min_speech_s: float,
        pad_s: float,
        origin: float = 0.0,
    ) -> None:
        self._stream = stream
        self._window_s = window / rate
        self._threshold = threshold
        self._silence_windows = max(1, math.ceil(silence_s / self._window_s - 1e-9))
        self._max_windows = max(2, int(max_s / self._window_s))
        self._min_speech_windows = max(1, math.ceil(min_speech_s / self._window_s - 1e-9))
        self._pad_windows = max(0, round(pad_s / self._window_s))
        self._offset = origin
        self._windows_seen = 0
        self._preroll: deque[Samples] = deque(maxlen=max(1, self._pad_windows))
        self._buffer: list[Samples] = []
        self._energy: list[float] = []
        self._start_index = 0
        self._speech_windows = 0
        self._silence_run = 0

    @property
    def in_speech(self) -> bool:
        return bool(self._buffer)

    @property
    def speech_start(self) -> float | None:
        """Session time at which the speech in progress began; None between segments."""
        return self._offset + self._start_index * self._window_s if self._buffer else None

    @property
    def now(self) -> float:
        """Session time at the end of the last window pushed."""
        return self._offset + self._windows_seen * self._window_s

    def push(self, window: Samples, probability: float) -> AudioSegment | None:
        """Add one window; return a segment if one just closed."""
        index = self._windows_seen
        self._windows_seen += 1
        is_speech = probability >= self._threshold

        if not self._buffer:
            if not is_speech:
                if self._pad_windows:
                    self._preroll.append(window)
                return None
            preroll = list(self._preroll) if self._pad_windows else []
            self._preroll.clear()
            self._buffer = [*preroll, window]
            self._energy = [_rms(w) for w in self._buffer]
            self._start_index = index - len(preroll)
            self._speech_windows = 1
            self._silence_run = 0
            return None

        self._buffer.append(window)
        self._energy.append(_rms(window))
        if is_speech:
            self._speech_windows += 1
            self._silence_run = 0
        else:
            self._silence_run += 1

        if self._silence_run >= self._silence_windows:
            keep = len(self._buffer) - self._silence_run + self._pad_windows
            return self._close(keep)
        if len(self._buffer) >= self._max_windows:
            return self._cut()
        return None

    def flush(self) -> AudioSegment | None:
        """Close any speech in progress (end of stream or session)."""
        if not self._buffer:
            return None
        keep = len(self._buffer) - max(0, self._silence_run - self._pad_windows)
        return self._close(keep)

    def skip(self, seconds: float) -> AudioSegment | None:
        """Time passed with no audio: close speech in progress and move the clock on."""
        closed = self.flush()
        self._preroll.clear()
        self._offset += max(0.0, seconds)
        return closed

    def _close(self, keep: int) -> AudioSegment | None:
        windows = self._buffer[:keep]
        segment = (
            self._segment(windows) if self._speech_windows >= self._min_speech_windows else None
        )
        self._buffer = []
        self._energy = []
        self._silence_run = 0
        self._speech_windows = 0
        return segment

    def _cut(self) -> AudioSegment | None:
        """Forced cut at the quietest window of the last second."""
        last_second = max(1, round(1.0 / self._window_s))
        start = max(1, len(self._energy) - last_second)
        tail = self._energy[start:]
        cut = start + int(np.argmin(tail))  # the quietest window ends the segment
        windows = self._buffer[: cut + 1]
        segment = self._segment(windows)
        self._buffer = self._buffer[cut + 1 :]
        self._energy = self._energy[cut + 1 :]
        self._start_index += cut + 1
        self._speech_windows = len(self._buffer)  # still mid-sentence
        self._silence_run = 0
        return segment

    def _segment(self, windows: list[Samples]) -> AudioSegment:
        t_start = self._offset + self._start_index * self._window_s
        return AudioSegment(
            stream=self._stream,
            t_start=t_start,
            t_end=t_start + len(windows) * self._window_s,
            samples=np.concatenate(windows).astype(np.float32, copy=False),
        )


def _rms(window: Samples) -> float:
    return float(np.sqrt(np.mean(np.square(window, dtype=np.float64))))
