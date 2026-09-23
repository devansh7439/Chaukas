"""The speech-to-text backend named in the config (``asr.backend``), ready to use.

``onnx`` (the default) runs on ONNX Runtime, on x64 and on Windows on ARM64. ``ctranslate2``
is faster-whisper, which has no ARM64 build. Both load models from disk only; ``download``
is the one step that uses the network (``chaukas setup``).
"""

from __future__ import annotations

from pathlib import Path

from chaukas.asr.base import ModelMissingError, Transcriber
from chaukas.core.config import ASRConfig
from chaukas.core.errors import ChaukasError


def load_transcriber(asr: ASRConfig) -> Transcriber:
    if asr.backend == "onnx":
        from chaukas.asr.whisper_onnx import WhisperOnnx, find_model

        folder = find_model(asr.model)
        if folder is None:
            raise ModelMissingError(
                f"the Whisper model {asr.model!r} (ONNX) is not on this PC; "
                "download it with: chaukas setup"
            )
        return WhisperOnnx(folder, language=asr.language, cpu_threads=asr.cpu_threads,
                           no_speech_threshold=asr.no_speech_threshold)  # fmt: skip
    try:
        import faster_whisper  # noqa: F401  (fail here, with a clear message)

        from chaukas.asr.whisper_cpu import WhisperCpu
    except ImportError as exc:
        raise ChaukasError(
            "faster-whisper is not installed (it has no Windows ARM64 build); "
            "set asr: backend: onnx"
        ) from exc
    return WhisperCpu(asr.model, language=asr.language, cpu_threads=asr.cpu_threads,
                      beam_size=asr.beam_size, no_speech_threshold=asr.no_speech_threshold,
                      hotwords=asr.hotwords)  # fmt: skip


def model_ready(asr: ASRConfig) -> bool:
    """Is the configured model on this PC? (Never downloads.)"""
    try:
        load_transcriber(asr)
    except ModelMissingError:
        return False
    return True


def download(asr: ASRConfig) -> Path:
    """Fetch the configured model into the local cache."""
    if asr.backend == "onnx":
        from chaukas.asr.whisper_onnx import download as download_onnx

        return download_onnx(asr.model)
    from chaukas.asr.whisper_cpu import download as download_ctranslate2

    return download_ctranslate2(asr.model)
