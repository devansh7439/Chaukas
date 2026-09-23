"""Where the voice detection model lives, and fetching it (hash-checked) with chaukas setup."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("onnxruntime")

from chaukas.audio import vad
from chaukas.core.errors import ChaukasError
from chaukas.core.paths import models_dir


class TestModelsDir:
    def test_an_environment_variable_overrides_the_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CHAUKAS_MODELS", str(tmp_path))
        assert models_dir() == tmp_path

    def test_the_default_is_the_local_app_data_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CHAUKAS_MODELS", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert models_dir() == tmp_path / "Chaukas" / "models"


class TestVadModel:
    def test_a_downloaded_model_is_found_first(self, tmp_path: Path) -> None:
        (tmp_path / vad.MODEL_NAME).write_bytes(b"model")
        assert vad.find_vad_model(tmp_path) == tmp_path / vad.MODEL_NAME

    def test_download_checks_the_hash_and_saves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = b"pretend onnx bytes"
        monkeypatch.setattr(vad, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
        path = vad.download_vad_model(tmp_path, fetch=lambda url: payload)
        assert path == tmp_path / vad.MODEL_NAME
        assert path.read_bytes() == payload

    def test_download_refuses_a_file_with_the_wrong_hash(self, tmp_path: Path) -> None:
        with pytest.raises(ChaukasError, match="SHA-256"):
            vad.download_vad_model(tmp_path, fetch=lambda url: b"tampered")
        assert not (tmp_path / vad.MODEL_NAME).exists()

    def test_the_pinned_url_is_a_release_tag_not_a_branch(self) -> None:
        assert "/raw/v1.2.1/" in vad.MODEL_URL
