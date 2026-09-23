"""Device audio -> the 16 kHz mono float32 that voice detection and Whisper expect.

Capture delivers interleaved 16-bit PCM at the device's own rate and channel count
(usually 48 kHz stereo). Channels are averaged, then a streaming resampler (soxr) converts
chunk by chunk without clicks at chunk boundaries.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt
import soxr

TARGET_RATE: Final = 16_000

Samples = npt.NDArray[np.float32]


def pcm16_to_float(raw: bytes) -> Samples:
    """Little-endian signed 16-bit PCM -> float32 in [-1, 1)."""
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


class StreamResampler:
    """Interleaved frames at ``in_rate`` with ``channels`` -> mono at 16 kHz, streaming."""

    __slots__ = ("_channels", "_stream")

    def __init__(self, in_rate: int, channels: int, out_rate: int = TARGET_RATE) -> None:
        if channels < 1:
            raise ValueError(f"channels must be at least 1, got {channels}")
        self._channels = channels
        self._stream = (
            soxr.ResampleStream(in_rate, out_rate, 1, dtype="float32", quality="HQ")
            if in_rate != out_rate
            else None
        )

    def process(self, interleaved: Samples) -> Samples:
        mono = self._downmix(interleaved)
        if self._stream is None:
            return mono
        return np.asarray(self._stream.resample_chunk(mono, last=False), dtype=np.float32)

    def flush(self) -> Samples:
        """The resampler's remaining samples (end of stream)."""
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        empty = np.zeros(0, dtype=np.float32)
        return np.asarray(self._stream.resample_chunk(empty, last=True), dtype=np.float32)

    def _downmix(self, interleaved: Samples) -> Samples:
        samples = np.asarray(interleaved, dtype=np.float32)
        if self._channels == 1:
            return samples
        usable = len(samples) - len(samples) % self._channels
        frames = samples[:usable].reshape(-1, self._channels)
        return frames.mean(axis=1).astype(np.float32)
