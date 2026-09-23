"""Choosing the speech-to-text backend from the config."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chaukas.asr.base import ModelMissingError
from chaukas.asr.loader import load_transcriber, model_ready
from chaukas.core.config import load_config
from chaukas.core.errors import ChaukasError

ASR = load_config().asr


def with_backend(backend: str, model: str = "small") -> object:
    return ASR.model_copy(update={"backend": backend, "model": model})


class TestLoader:
    def test_onnx_is_the_default_backend(self) -> None:
        assert ASR.backend == "onnx"

    def test_the_onnx_backend_loads_when_the_model_is_downloaded(self) -> None:
        pytest.importorskip("onnxruntime")
        pytest.importorskip("tokenizers")
        from chaukas.asr.whisper_onnx import WhisperOnnx, find_model

        if find_model("small") is None:
            pytest.skip("the ONNX Whisper model is not downloaded")
        assert isinstance(load_transcriber(with_backend("onnx")), WhisperOnnx)  # type: ignore[arg-type]
        assert model_ready(with_backend("onnx"))  # type: ignore[arg-type]

    def test_a_model_that_is_not_downloaded_says_how_to_get_it(self) -> None:
        pytest.importorskip("onnxruntime")
        pytest.importorskip("tokenizers")
        missing = with_backend("onnx", model="no-such-size")
        assert not model_ready(missing)  # type: ignore[arg-type]
        with pytest.raises(ModelMissingError, match="chaukas setup"):
            load_transcriber(missing)  # type: ignore[arg-type]

    def test_ctranslate2_without_faster_whisper_points_to_the_onnx_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "faster_whisper", None)  # as on Windows on ARM64
        with pytest.raises(ChaukasError, match="backend: onnx"):
            load_transcriber(with_backend("ctranslate2"))  # type: ignore[arg-type]

    def test_models_folder_is_not_touched_by_a_readiness_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CHAUKAS_MODELS", str(tmp_path / "models"))
        model_ready(with_backend("onnx", model="no-such-size"))  # type: ignore[arg-type]
        assert not (tmp_path / "models").exists()
