"""Silero voice activity detection (v6, ONNX), streaming.

The model scores 512-sample windows (32 ms at 16 kHz). Each window is given the last 64
samples of the previous one as context, and the LSTM state is carried from window to
window, so feeding audio chunk by chunk gives the same result as feeding it all at once.
Runs on one CPU thread; a window takes well under a millisecond.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Final

import numpy as np
import onnxruntime as ort

from chaukas.audio.convert import Samples

WINDOW: Final = 512
CONTEXT: Final = 64
MODEL_NAME: Final = "silero_vad_v6.onnx"


def find_vad_model(models_dir: Path | None = None) -> Path | None:
    """A downloaded model in ``models_dir``, else the copy bundled with faster-whisper."""
    if models_dir is not None and (models_dir / MODEL_NAME).is_file():
        return models_dir / MODEL_NAME
    try:
        bundled = resources.files("faster_whisper.assets").joinpath(MODEL_NAME)
    except ModuleNotFoundError:
        return None
    path = Path(str(bundled))
    return path if path.is_file() else None


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
