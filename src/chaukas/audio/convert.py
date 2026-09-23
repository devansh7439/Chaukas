"""Device audio -> the 16 kHz mono float32 that voice detection and Whisper expect.

Capture delivers interleaved 16-bit PCM at the device's own rate and channel count
(usually 48 kHz stereo). Channels are averaged, then a streaming resampler converts chunk
by chunk without clicks at chunk boundaries.

The resampler is plain numpy (no native library, so it installs on Windows on ARM64):
a Kaiser-windowed low-pass filter below 7.2 kHz removes everything that would alias,
then output samples are read at fractional positions by linear interpolation, which is
accurate here because the filtered signal is oversampled at least 2.7 times. Both the
filter's history and the fractional position carry over from one chunk to the next.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
import numpy.typing as npt

TARGET_RATE: Final = 16_000
_CUTOFF: Final = 0.9  # of the output Nyquist frequency (7.2 kHz at 16 kHz)
_KAISER_BETA: Final = 8.0  # about 80 dB of stop-band attenuation
_TAPS_PER_STEP: Final = 8  # filter half-length, in multiples of the decimation step

Samples = npt.NDArray[np.float32]


def pcm16_to_float(raw: bytes) -> Samples:
    """Little-endian signed 16-bit PCM -> float32 in [-1, 1)."""
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _lowpass(in_rate: int, out_rate: int) -> npt.NDArray[np.float64]:
    step = in_rate / out_rate
    half = max(8, round(_TAPS_PER_STEP * step))
    n = np.arange(-half, half + 1, dtype=np.float64)
    cutoff = _CUTOFF * (out_rate / 2) / in_rate  # cycles per input sample
    taps = 2 * cutoff * np.sinc(2 * cutoff * n) * np.kaiser(len(n), _KAISER_BETA)
    return taps / taps.sum()


class StreamResampler:
    """Interleaved frames at ``in_rate`` with ``channels`` -> mono at 16 kHz, streaming."""

    __slots__ = ("_carry", "_channels", "_history", "_pos", "_step", "_taps")

    def __init__(self, in_rate: int, channels: int, out_rate: int = TARGET_RATE) -> None:
        if channels < 1:
            raise ValueError(f"channels must be at least 1, got {channels}")
        if in_rate <= 0 or out_rate <= 0:
            raise ValueError(f"rates must be positive, got {in_rate} and {out_rate}")
        self._channels = channels
        self._step = in_rate / out_rate
        self._taps = _lowpass(in_rate, out_rate) if in_rate != out_rate else None
        width = 0 if self._taps is None else len(self._taps) - 1
        self._history = np.zeros(width, dtype=np.float64)
        self._carry = np.zeros(0, dtype=np.float64)  # filtered samples not yet consumed
        self._pos = 0.0  # position of the next output sample within the carry

    def process(self, interleaved: Samples) -> Samples:
        mono = self._downmix(interleaved)
        if self._taps is None:
            return mono
        return self._resample(mono.astype(np.float64))

    def flush(self) -> Samples:
        """Push the filter's delay out (end of stream)."""
        if self._taps is None:
            return np.zeros(0, dtype=np.float32)
        return self._resample(np.zeros(len(self._taps) // 2, dtype=np.float64))

    def _resample(self, samples: npt.NDArray[np.float64]) -> Samples:
        assert self._taps is not None
        padded = np.concatenate([self._history, samples])
        filtered = np.convolve(padded, self._taps, mode="valid")
        if len(self._history):
            self._history = padded[-len(self._history) :]
        buffer = np.concatenate([self._carry, filtered])
        last = len(buffer) - 1  # an output needs the sample after its position too
        if last <= self._pos:
            self._carry = buffer
            return np.zeros(0, dtype=np.float32)
        count = math.floor((last - self._pos) / self._step) + 1
        positions = self._pos + self._step * np.arange(count)
        base = np.floor(positions).astype(np.int64)
        base = np.minimum(base, last - 1)
        fraction = positions - base
        out = buffer[base] * (1 - fraction) + buffer[base + 1] * fraction
        next_pos = self._pos + self._step * count
        drop = min(math.floor(next_pos), len(buffer))
        self._carry = buffer[drop:]
        self._pos = next_pos - drop
        result: Samples = out.astype(np.float32)
        return result

    def _downmix(self, interleaved: Samples) -> Samples:
        samples = np.asarray(interleaved, dtype=np.float32)
        if self._channels == 1:
            return samples
        usable = len(samples) - len(samples) % self._channels
        frames = samples[:usable].reshape(-1, self._channels)
        mono: Samples = frames.mean(axis=1).astype(np.float32)
        return mono
