"""Whisper on the CPU via faster-whisper (CTranslate2, int8): the development backend.

Models load from the local cache only, so a live session never touches the network;
``download`` fetches one once (``chaukas setup``).

Two Whisper habits are handled here:

* On silence or noise Whisper can hallucinate a stock phrase ("Thank you."). Segments whose
  no-speech probability is above ``no_speech_threshold`` are dropped.
* With automatic language detection, Hindi is sometimes labelled Urdu and written in Urdu
  script, which the lexicon cannot read. Such a segment is transcribed again as Hindi.

Detecting the language costs a second encoder pass (about double the time), so callers
pass the speaker's language as a hint once it is known.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Final, Protocol

from chaukas.asr.base import ModelMissingError, Transcript
from chaukas.audio.convert import Samples

_RETRY_AS_HINDI: Final = frozenset({"ur"})

__all__ = ["ModelMissingError", "WhisperCpu", "download"]


class _Model(Protocol):
    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Any, Any]: ...


class WhisperCpu:
    __slots__ = ("_beam_size", "_hotwords", "_language", "_model", "_no_speech")

    def __init__(
        self,
        model: str,
        *,
        language: str,
        cpu_threads: int,
        beam_size: int,
        no_speech_threshold: float,
        hotwords: str = "",
    ) -> None:
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        from faster_whisper import WhisperModel

        try:
            loaded = WhisperModel(
                model, device="cpu", compute_type="int8", cpu_threads=cpu_threads,
                local_files_only=True,
            )  # fmt: skip
        except Exception as exc:  # the hub raises several unrelated types for "not cached"
            raise ModelMissingError(
                f"the Whisper model {model!r} is not on this PC; download it with: chaukas setup"
            ) from exc
        self._init(loaded, language, beam_size, no_speech_threshold, hotwords)

    @classmethod
    def from_model(
        cls,
        model: _Model,
        *,
        language: str,
        beam_size: int,
        no_speech_threshold: float,
        hotwords: str = "",
    ) -> WhisperCpu:
        """Wrap an already-loaded model (tests, or a model shared between sessions)."""
        instance = cls.__new__(cls)
        instance._init(model, language, beam_size, no_speech_threshold, hotwords)
        return instance

    def _init(
        self,
        model: _Model,
        language: str,
        beam_size: int,
        no_speech_threshold: float,
        hotwords: str,
    ) -> None:
        self._model = model
        self._language = language
        self._beam_size = beam_size
        self._no_speech = no_speech_threshold
        self._hotwords = hotwords or None

    def transcribe(self, samples: Samples, *, language: str | None = None) -> Transcript:
        start = time.perf_counter()
        fixed = language if self._language == "auto" else self._language
        text, detected = self._run(samples, fixed)
        if fixed is None and detected in _RETRY_AS_HINDI:
            text, detected = self._run(samples, "hi")
        return Transcript(text=text, language=detected, ms=(time.perf_counter() - start) * 1000)

    def _run(self, samples: Samples, language: str | None) -> tuple[str, str | None]:
        segments, info = self._model.transcribe(
            samples,
            language=language,
            beam_size=self._beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
            without_timestamps=True,
            hotwords=self._hotwords,
        )
        kept = [s.text.strip() for s in segments if s.no_speech_prob < self._no_speech]
        return " ".join(part for part in kept if part), getattr(info, "language", None)


def download(model: str) -> Path:
    """Fetch a model into the local cache (the one step that uses the network)."""
    from faster_whisper import download_model

    return Path(download_model(model))
