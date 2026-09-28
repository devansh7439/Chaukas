"""``chaukas benchmark asr``: reproducible speech-recognition timing, with the hardware used."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("onnxruntime")
pytest.importorskip("tokenizers")

from chaukas.asr.benchmark import benchmark  # noqa: E402
from chaukas.asr.whisper_onnx import WhisperOnnx, find_model  # noqa: E402


@pytest.fixture(scope="module")
def folder() -> Path:
    path = find_model("small")
    if path is None:
        pytest.skip("the ONNX Whisper model is not downloaded")
    return path


def test_reports_timings_providers_and_real_time_factor(
    folder: Path, speech: Callable[[str], object]
) -> None:
    whisper = WhisperOnnx(folder, language="auto", cpu_threads=8, no_speech_threshold=0.6)
    audio = speech("This is the CBI cyber cell. Tell me the OTP you just received.")
    result = benchmark(whisper, audio, runs=2, model="whisper-small")  # type: ignore[arg-type]
    assert result["runs"] == 2
    assert result["encoder_providers"][0] == "CPUExecutionProvider"
    assert result["audio_s"] == pytest.approx(len(audio) / 16_000, abs=0.01)  # type: ignore[arg-type]
    assert result["total_ms"] >= result["encoder_ms"] > 0
    assert result["rtf"] == pytest.approx(result["total_ms"] / 1000 / result["audio_s"], rel=0.01)
    assert result["fallback"] is False
    assert "OTP" in result["text"]
    assert result["on_battery"] in (True, False, None)  # recorded: it changes the numbers
    assert result["peak_memory_mb"] is None or result["peak_memory_mb"] > 100.0  # the model
    json.dumps(result)  # serialisable as it is


def test_a_requested_npu_that_is_not_available_is_reported_as_a_fallback(
    folder: Path, speech: Callable[[str], object]
) -> None:
    import onnxruntime as ort

    if "QNNExecutionProvider" in ort.get_available_providers():
        pytest.skip("this machine has the QNN provider")
    whisper = WhisperOnnx(folder, language="auto", cpu_threads=8, no_speech_threshold=0.6,
                          device="npu")  # fmt: skip
    result = benchmark(whisper, speech("Tell me the OTP."), runs=1, model="whisper-small")  # type: ignore[arg-type]
    assert result["requested_device"] == "npu"
    assert result["device"] == "cpu"
    assert result["fallback"] is True
    assert "QNN" in result["note"]


def test_peak_memory_is_reported_where_windows_can_measure_it() -> None:
    import sys

    from chaukas.asr.benchmark import peak_memory_mb

    peak = peak_memory_mb()
    if sys.platform == "win32":
        assert peak is not None
        assert peak > 10.0  # this Python process with numpy and onnxruntime loaded
    else:
        assert peak is None
