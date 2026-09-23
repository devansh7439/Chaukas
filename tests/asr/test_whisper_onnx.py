"""Whisper on ONNX Runtime: the backend that also runs on Windows on ARM64 (Snapdragon)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("onnxruntime")
pytest.importorskip("tokenizers")

from chaukas.asr.whisper_cpu import ModelMissingError  # noqa: E402
from chaukas.asr.whisper_onnx import WhisperOnnx, find_model  # noqa: E402

RATE = 16_000


@pytest.fixture(scope="module")
def whisper() -> WhisperOnnx:
    folder = find_model("small")
    if folder is None:
        pytest.skip("the ONNX Whisper model is not downloaded (chaukas setup)")
    return WhisperOnnx(folder, language="auto", cpu_threads=8, no_speech_threshold=0.6)


class TestTranscribe:
    def test_hears_an_english_sentence(
        self, whisper: WhisperOnnx, speech: Callable[[str], object]
    ) -> None:
        transcript = whisper.transcribe(speech("Please tell me the OTP you just received."))  # type: ignore[arg-type]
        assert "OTP" in transcript.text
        assert "received" in transcript.text
        assert transcript.language == "en"
        assert transcript.ms > 0

    def test_a_language_hint_skips_detection_and_gives_the_same_text(
        self, whisper: WhisperOnnx, speech: Callable[[str], object]
    ) -> None:
        audio = speech("An arrest warrant has been issued in your name.")
        detected = whisper.transcribe(audio)  # type: ignore[arg-type]
        hinted = whisper.transcribe(audio, language="en")  # type: ignore[arg-type]
        assert hinted.text == detected.text
        assert "arrest warrant" in hinted.text.lower()

    def test_silence_gives_no_text(self, whisper: WhisperOnnx) -> None:
        assert whisper.transcribe(np.zeros(RATE * 2, dtype=np.float32)).text == ""

    def test_noise_gives_no_text(self, whisper: WhisperOnnx) -> None:
        rng = np.random.default_rng(3)
        noise = (0.01 * rng.standard_normal(RATE * 3)).astype(np.float32)
        assert whisper.transcribe(noise).text == ""

    def test_a_fixed_language_in_the_config_wins_over_the_hint(
        self, speech: Callable[[str], object]
    ) -> None:
        folder = find_model("small")
        if folder is None:
            pytest.skip("the ONNX Whisper model is not downloaded")
        english = WhisperOnnx(folder, language="en", cpu_threads=8, no_speech_threshold=0.6)
        transcript = english.transcribe(speech("Do not tell anyone."), language="hi")  # type: ignore[arg-type]
        assert transcript.language == "en"
        assert "tell anyone" in transcript.text.lower()


class TestModelFiles:
    def test_a_missing_model_says_how_to_get_it(self, tmp_path: Path) -> None:
        with pytest.raises(ModelMissingError, match="chaukas setup"):
            WhisperOnnx(tmp_path, language="auto", cpu_threads=2, no_speech_threshold=0.6)
