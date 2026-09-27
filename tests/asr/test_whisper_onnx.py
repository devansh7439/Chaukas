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


class TestDevices:
    """The encoder can run on the Snapdragon NPU; protection never depends on it."""

    def test_the_cpu_runtime_reports_its_real_providers(self, whisper: WhisperOnnx) -> None:
        runtime = whisper.runtime
        assert runtime.device == "cpu"
        assert runtime.encoder_providers[0] == "CPUExecutionProvider"
        assert runtime.decoder_providers[0] == "CPUExecutionProvider"
        assert runtime.note == ""

    def test_asking_for_the_npu_without_it_falls_back_to_the_cpu_and_says_why(
        self, speech: Callable[[str], object]
    ) -> None:
        import onnxruntime as ort

        if "QNNExecutionProvider" in ort.get_available_providers():
            pytest.skip("this machine has the QNN provider: the NPU path is used instead")
        folder = find_model("small")
        if folder is None:
            pytest.skip("the ONNX Whisper model is not downloaded")
        whisper = WhisperOnnx(folder, language="auto", cpu_threads=8, no_speech_threshold=0.6,
                              device="npu")  # fmt: skip
        assert whisper.runtime.device == "cpu"
        assert whisper.runtime.requested == "npu"
        assert "QNN" in whisper.runtime.note
        transcript = whisper.transcribe(speech("Tell me the OTP."))  # type: ignore[arg-type]
        assert "OTP" in transcript.text  # protection continues on the CPU

    def test_each_call_times_the_encoder_and_the_decoder(
        self, whisper: WhisperOnnx, speech: Callable[[str], object]
    ) -> None:
        transcript = whisper.transcribe(speech("Share the OTP now, sir."))  # type: ignore[arg-type]
        timing = whisper.last_timing
        assert timing is not None
        assert timing.encoder_ms > 0
        assert timing.decoder_ms > 0
        assert timing.encoder_ms + timing.decoder_ms <= transcript.ms + 1.0
