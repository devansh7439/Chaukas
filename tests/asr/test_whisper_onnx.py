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


class TestPrecision:
    """Review finding: the benchmark called everything "int8", but on the NPU the encoder is
    the fp32 model run in fp16 by QNN, while the decoder stays int8 on the CPU."""

    def test_the_cpu_runtime_is_int8_throughout(self, whisper: WhisperOnnx) -> None:
        assert whisper.runtime.encoder_precision == "int8 model on the CPU"
        assert whisper.runtime.decoder_precision == "int8 model on the CPU"

    @staticmethod
    def npu_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, fp16: bool) -> str:
        import sys
        from types import SimpleNamespace

        from chaukas.asr.whisper_onnx import _npu_encoder

        name = "QNNExecutionProvider"
        monkeypatch.setitem(sys.modules, "onnxruntime_qnn", SimpleNamespace(
            get_ep_name=lambda: name, get_library_path=lambda: "QnnHtp.dll"))  # fmt: skip

        class Options:
            def __init__(self) -> None:
                self.chosen: dict[str, str] = {}

            def add_provider_for_devices(self, devices: object, options: dict[str, str]) -> None:
                self.chosen = options

        class Session:
            def __init__(self, path: str, sess_options: Options) -> None:
                if "enable_htp_fp16_precision" in sess_options.chosen and not fp16:
                    raise RuntimeError("fp16 not supported by this backend")

            def get_providers(self) -> list[str]:
                return [name, "CPUExecutionProvider"]

        npu = SimpleNamespace(ep_name=name, device=SimpleNamespace(type="NPU"))
        ort = SimpleNamespace(
            get_ep_devices=lambda: [npu], register_execution_provider_library=lambda *a: None,
            OrtHardwareDeviceType=SimpleNamespace(NPU="NPU"), SessionOptions=Options,
            InferenceSession=Session,
        )  # fmt: skip
        encoder = tmp_path / "encoder_model.onnx"
        encoder.write_bytes(b"onnx")
        _, precision = _npu_encoder(ort, encoder, 4)
        return str(precision)

    def test_the_npu_encoder_reports_fp32_weights_run_in_fp16(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        precision = self.npu_session(monkeypatch, tmp_path, fp16=True)
        assert precision == "fp32 model, run in fp16 on the NPU (QNN HTP)"

    def test_without_fp16_it_says_the_backend_chose(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        precision = self.npu_session(monkeypatch, tmp_path, fp16=False)
        assert precision == "fp32 model, the NPU backend's default precision (QNN HTP)"
