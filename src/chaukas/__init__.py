"""Chaukas: an on-device AI guardian against social engineering."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("chaukas")
except PackageNotFoundError:  # pragma: no cover - source tree without an install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
