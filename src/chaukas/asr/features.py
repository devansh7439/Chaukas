"""Whisper's input: an 80-band log-mel spectrogram of 30 s of 16 kHz audio (blueprint 6.2).

Computed exactly as the reference does (OpenAI Whisper, Hugging Face): audio padded with
zeros to 30 s, a reflect-padded STFT (400-sample periodic Hann window, 160-sample hop),
power spectrum, Slaney-style mel filters, then ``log10``, clamped to 8 below the peak and
scaled to about [-1, 1]. Plain numpy, so it runs wherever numpy does (Windows on ARM64).
"""

from __future__ import annotations

from functools import cache
from typing import Final

import numpy as np
import numpy.typing as npt

from chaukas.audio.convert import TARGET_RATE, Samples

N_FFT: Final = 400
HOP: Final = 160
N_MELS: Final = 80
N_SAMPLES: Final = 30 * TARGET_RATE
FRAMES: Final = N_SAMPLES // HOP  # 3000

Features = npt.NDArray[np.float32]


def log_mel(samples: Samples) -> Features:
    """16 kHz mono audio (cut at 30 s) -> float32 features of shape (80, 3000)."""
    audio = np.zeros(N_SAMPLES, dtype=np.float32)
    clip = np.asarray(samples, dtype=np.float32)[:N_SAMPLES]
    audio[: len(clip)] = clip
    padded = np.pad(audio, N_FFT // 2, mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, N_FFT)[::HOP][:FRAMES]
    power = np.abs(np.fft.rfft(frames * _window(), axis=1)) ** 2  # (3000, 201)
    mel = _mel_filters() @ power.T  # (80, 3000)
    log = np.log10(np.maximum(mel, 1e-10))
    log = np.maximum(log, log.max() - 8.0)
    features: Features = ((log + 4.0) / 4.0).astype(np.float32)
    return features


@cache
def _window() -> npt.NDArray[np.float64]:
    return np.hanning(N_FFT + 1)[:-1]  # periodic Hann


@cache
def _mel_filters() -> npt.NDArray[np.float64]:
    """Slaney mel filter bank (as librosa's ``mel(sr=16000, n_fft=400, n_mels=80)``)."""
    fft_freqs = np.fft.rfftfreq(N_FFT, d=1.0 / TARGET_RATE)
    mels = np.linspace(0.0, _hz_to_mel(TARGET_RATE / 2), N_MELS + 2)
    freqs = _mel_to_hz(mels)
    spacing = np.diff(freqs)
    ramps = freqs[:, None] - fft_freqs[None, :]
    lower = -ramps[:-2] / spacing[:-1, None]
    upper = ramps[2:] / spacing[1:, None]
    weights = np.maximum(0.0, np.minimum(lower, upper))
    weights *= (2.0 / (freqs[2:] - freqs[:-2]))[:, None]  # equal energy per band
    return weights


# Slaney's mel scale: linear below 1 kHz, logarithmic above.
_F_SP: Final = 200.0 / 3
_MIN_LOG_HZ: Final = 1000.0
_MIN_LOG_MEL: Final = _MIN_LOG_HZ / _F_SP
_LOG_STEP: Final = np.log(6.4) / 27.0


def _hz_to_mel(hz: float) -> float:
    if hz < _MIN_LOG_HZ:
        return hz / _F_SP
    return float(_MIN_LOG_MEL + np.log(hz / _MIN_LOG_HZ) / _LOG_STEP)


def _mel_to_hz(mels: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    linear = _F_SP * mels
    log = _MIN_LOG_HZ * np.exp(_LOG_STEP * (mels - _MIN_LOG_MEL))
    result: npt.NDArray[np.float64] = np.where(mels >= _MIN_LOG_MEL, log, linear)
    return result
