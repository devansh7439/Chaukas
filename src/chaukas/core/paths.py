"""Where Chaukas keeps downloaded models on this PC."""

from __future__ import annotations

import os
from pathlib import Path


def models_dir() -> Path:
    """``CHAUKAS_MODELS`` if set, else ``%LOCALAPPDATA%\\Chaukas\\models`` (not roaming:
    models are large and belong to this machine)."""
    override = os.environ.get("CHAUKAS_MODELS")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "Chaukas" / "models"
