"""Silero voice activity detection (v6, ONNX), streaming.

The model scores 512-sample windows (32 ms at 16 kHz). Each window is given the last 64
samples of the previous one as context, and the LSTM state is carried from window to
window, so feeding audio chunk by chunk gives the same result as feeding it all at once.
Runs on one CPU thread; a window takes well under a millisecond.
"""

from __future__ import annotations

import hashlib
import urllib.request
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Final

import numpy as np
import onnxruntime as ort

from chaukas.audio.convert import Samples
from chaukas.core.errors import ChaukasError
from chaukas.core.paths import models_dir

WINDOW: Final = 512
CONTEXT: Final = 64
MODEL_NAME: Final = "silero_vad_v6.onnx"


# Silero VAD v6 (MIT), as re-exported by faster-whisper with separate h/c state inputs.
# Pinned to a release tag and checked by hash, so the file cannot change under us.
MODEL_URL: Final = (
    "https://github.com/SYSTRAN/faster-whisper/raw/v1.2.1/faster_whisper/assets/" + MODEL_NAME
)
MODEL_SHA256: Final = "4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2"


def find_vad_model(folder: Path | None = None) -> Path | None:
    """The downloaded model (in ``folder``, default the models folder), else the copy
    bundled with faster-whisper where that is installed (not on Windows on ARM64)."""
    folder = folder if folder is not None else models_dir()
    if (folder / MODEL_NAME).is_file():
        return folder / MODEL_NAME
    try:
        bundled = resources.files("faster_whisper.assets").joinpath(MODEL_NAME)
    except ModuleNotFoundError:
        return None
    path = Path(str(bundled))
    return path if path.is_file() else None


def download_vad_model(
    folder: Path | None = None, *, fetch: Callable[[str], bytes] | None = None
) -> Path:
    """Fetch the model into ``folder`` (``chaukas setup``); refuse it if the hash differs."""
    folder = folder if folder is not None else models_dir()
    data = (fetch or _fetch)(MODEL_URL)
    digest = hashlib.sha256(data).hexdigest()
    if digest != MODEL_SHA256:
        raise ChaukasError(
            f"the voice detection model's SHA-256 is {digest}, expected {MODEL_SHA256}; not saved"
        )
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / MODEL_NAME
    partial = path.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(path)
    return path


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        data: bytes = response.read()
    return data


class SileroVad:
    __slots__ = ("_c", "_context", "_h", "_pending", "_session")

    def __init__(self, model: Path) -> None:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(model), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)

    def process(self, samples: Samples) -> list[tuple[Samples, float]]:
        """(window, speech probability) for every complete window; the rest waits."""
        buffer = np.concatenate([self._pending, np.asarray(samples, dtype=np.float32)])
        count = len(buffer) // WINDOW
        results: list[tuple[Samples, float]] = []
        for i in range(count):
            window = buffer[i * WINDOW : (i + 1) * WINDOW]
            frame = np.concatenate([self._context, window])[np.newaxis, :]
            probability, self._h, self._c = self._session.run(
                None, {"input": frame, "h": self._h, "c": self._c}
            )
            self._context = window[-CONTEXT:]
            results.append((window, float(np.ravel(probability)[0])))
        self._pending = buffer[count * WINDOW :].copy()
        return results
