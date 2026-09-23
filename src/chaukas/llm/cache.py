"""On-disk cache of LLM completions, for reproducible evaluation (blueprint 8.5).

The perception pass calls the real model once per distinct prompt and stores the answer
with its measured latency. Later engine passes replay the cache on a virtual clock, so a
result becomes visible at its request time plus the latency that was actually measured.

Keys are a hash of the model name and the full message list, so any change to the prompt,
transcript or state is a miss. Failures are not cached. The cache holds transcript text:
use it only with synthetic evaluation data (``eval/cache/`` is git-ignored).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from chaukas.core.errors import LLMUnavailableError
from chaukas.llm.client import Chat, ChatResult, Message

_KEY_CHARS: Final = 32


class CachedChat:
    __slots__ = ("_directory", "_inner", "_model", "_offline")

    def __init__(self, inner: Chat, directory: Path, *, model: str, offline: bool = False) -> None:
        self._inner = inner
        self._directory = directory
        self._model = model
        self._offline = offline

    def chat(self, messages: Sequence[Message]) -> ChatResult:
        path = self._directory / f"{self._key(messages)}.json"
        if path.is_file():
            stored = json.loads(path.read_text(encoding="utf-8"))
            return ChatResult(content=stored["content"], latency_s=float(stored["latency_s"]))
        if self._offline:
            raise LLMUnavailableError(f"prompt is not in the cache ({path.name})")
        result = self._inner.chat(messages)
        self._directory.mkdir(parents=True, exist_ok=True)
        record = {"model": self._model, "content": result.content, "latency_s": result.latency_s}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)  # atomic: a crash never leaves a half-written entry
        return result

    def _key(self, messages: Sequence[Message]) -> str:
        blob = json.dumps(
            {"model": self._model, "messages": [dict(m) for m in messages]},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:_KEY_CHARS]
