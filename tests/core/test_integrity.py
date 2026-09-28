"""Model files are checked against pinned hashes every time they are loaded, not only when
downloaded: a file changed on disk after setup is refused with a clear message."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from chaukas.core.integrity import ModelIntegrityError, verify


def test_a_file_matching_its_sha256_passes(tmp_path: Path) -> None:
    path = tmp_path / "model.onnx"
    path.write_bytes(b"weights")
    verify(path, sha256=hashlib.sha256(b"weights").hexdigest())


def test_a_file_matching_its_git_blob_hash_passes(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_bytes(b"{}")
    verify(path, git_sha1=hashlib.sha1(b"blob 2\0{}").hexdigest())


def test_a_modified_file_is_refused_and_named(tmp_path: Path) -> None:
    path = tmp_path / "model.onnx"
    path.write_bytes(b"weights, then tampered with")
    with pytest.raises(ModelIntegrityError, match=r"model\.onnx .*changed since it was downloaded"):
        verify(path, sha256=hashlib.sha256(b"weights").hexdigest())


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ModelIntegrityError, match="missing"):
        verify(tmp_path / "gone.onnx", sha256="0" * 64)


def test_a_check_needs_a_hash() -> None:
    with pytest.raises(ValueError, match="hash"):
        verify(Path("x"))


class TestModelsAreCheckedWhenLoaded:
    def test_whisper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("onnxruntime")
        pytest.importorskip("tokenizers")
        from chaukas.asr import whisper_onnx

        folder = whisper_onnx.find_model("small")
        if folder is None:
            pytest.skip("the ONNX Whisper model is not downloaded")
        monkeypatch.setitem(whisper_onnx.FILE_HASHES, "config.json", ("git_sha1", "0" * 40))
        with pytest.raises(ModelIntegrityError, match=r"config.json"):
            whisper_onnx.WhisperOnnx(folder, language="auto", cpu_threads=2,
                                     no_speech_threshold=0.6)  # fmt: skip

    def test_the_pinned_whisper_files_match_this_download(self) -> None:
        pytest.importorskip("onnxruntime")
        pytest.importorskip("tokenizers")
        from chaukas.asr import whisper_onnx

        folder = whisper_onnx.find_model("small")
        if folder is None:
            pytest.skip("the ONNX Whisper model is not downloaded")
        whisper_onnx.verify_files(folder, whisper_onnx.FILES)  # the upstream hashes

    def test_semantic_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("onnxruntime")
        pytest.importorskip("tokenizers")
        from chaukas.core.config import load_config
        from chaukas.signals import semantic

        if semantic.find_model() is None:
            pytest.skip("the semantic model is not downloaded")
        monkeypatch.setattr(semantic, "TOKENIZER_SHA256", "0" * 64)
        with pytest.raises(ModelIntegrityError, match=r"tokenizer.json"):
            semantic.load_semantic(load_config().signals.semantic)

    def test_voice_detection_model(self, tmp_path: Path) -> None:
        pytest.importorskip("onnxruntime")
        from chaukas.audio.vad import SileroVad, find_vad_model

        model = find_vad_model()
        if model is None:
            pytest.skip("the voice detection model is not downloaded")
        tampered = tmp_path / model.name
        tampered.write_bytes(model.read_bytes() + b"\0")
        with pytest.raises(ModelIntegrityError, match=re.escape(model.name)):
            SileroVad(tampered)
