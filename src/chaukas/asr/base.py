"""The speech-to-text interface every backend implements (blueprint 6.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from chaukas.audio.convert import Samples
from chaukas.core.errors import ChaukasError


class ModelMissingError(ChaukasError):
    """A model is not on this PC yet."""


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str  # empty if nothing intelligible was said
    language: str | None
    ms: float  # time spent transcribing


class Transcriber(Protocol):
    def transcribe(self, samples: Samples, *, language: str | None = None) -> Transcript:
        """16 kHz mono float32 audio of one segment -> its text.

        ``language`` is a hint (the speaker's language seen so far), which lets the backend
        skip language detection; ``None`` means detect it.
        """
        ...
