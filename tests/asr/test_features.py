"""Whisper's log-mel input features, in plain numpy (no native library, so ARM64 works)."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from chaukas.asr.features import FRAMES, N_SAMPLES, log_mel  # noqa: E402

RATE = 16_000


def tone(freq: float, seconds: float) -> object:
    t = np.arange(int(RATE * seconds)) / RATE
    return (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class TestLogMel:
    def test_shape_is_80_bands_by_3000_frames_for_any_length(self) -> None:
        for seconds in (0.5, 7.0, 30.0, 34.0):  # longer than 30 s is cut
            assert log_mel(tone(440.0, seconds)).shape == (80, FRAMES)

    def test_a_tone_lights_up_the_band_it_belongs_to(self) -> None:
        low = log_mel(tone(300.0, 2.0))[:, :100].mean(axis=1)
        high = log_mel(tone(3000.0, 2.0))[:, :100].mean(axis=1)
        assert int(np.argmax(low)) < int(np.argmax(high))

    def test_matches_the_reference_implementation(self) -> None:
        reference = pytest.importorskip("faster_whisper.feature_extractor")
        rng = np.random.default_rng(7)
        audio = np.concatenate([tone(220.0, 1.5), 0.05 * rng.standard_normal(RATE * 2)])
        audio = audio.astype(np.float32)
        padded = np.concatenate([audio, np.zeros(N_SAMPLES - len(audio), np.float32)])
        expected = reference.FeatureExtractor(feature_size=80)(padded, padding=0)
        assert expected.shape == (80, FRAMES)
        assert np.abs(log_mel(audio) - expected).max() < 1e-3

    def test_silence_does_not_divide_by_zero(self) -> None:
        features = log_mel(np.zeros(RATE, dtype=np.float32))
        assert np.isfinite(features).all()
