"""Model integrity: every model file is checked against a pinned hash each time it is loaded.

Downloads were already checked; this also catches a file changed on disk after setup (by
malware, or a broken disk). Hashes come from the publisher (Hugging Face's LFS SHA-256, or
git's blob id for small files), not from our own copy. Hashing the models takes well under
a second at start-up.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from chaukas.core.errors import ChaukasError

_CHUNK = 1 << 20


class ModelIntegrityError(ChaukasError):
    """A model file is missing or differs from the pinned version."""


def verify(path: Path, *, sha256: str | None = None, git_sha1: str | None = None) -> None:
    """Raise ModelIntegrityError unless ``path`` has the given SHA-256 or git blob id."""
    if sha256 is None and git_sha1 is None:
        raise ValueError("verify needs a hash: sha256 or git_sha1")
    if not path.is_file():
        raise ModelIntegrityError(f"{path.name} is missing from {path.parent}")
    kind, expected = ("SHA-256", sha256) if sha256 is not None else ("git blob id", git_sha1)
    actual = _sha256(path) if sha256 is not None else _git_blob_sha1(path)
    if actual != expected:
        raise ModelIntegrityError(
            f"{path.name} has changed since it was downloaded ({kind} {actual}, expected "
            f"{expected}); it was not loaded. Run: chaukas setup"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    """git's object id for a file: SHA-1 of "blob <size>\\0" and the bytes. It is the id the
    publisher's repository lists; SHA-1 is not our choice here."""
    digest = hashlib.sha1(f"blob {path.stat().st_size}\0".encode(), usedforsecurity=False)
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
