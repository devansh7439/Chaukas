"""Chat client for any OpenAI-compatible server: GenieX ``serve`` on Snapdragon, or a local
llama.cpp / Ollama / LM Studio server on a dev machine (blueprint 6.4).

Uses only the standard library: one JSON POST to ``/chat/completions``. That avoids the
``openai`` package's native dependencies, which may have no Windows-on-ARM64 wheels.

GenieX has no documented JSON-schema mode, so ``assess`` validates the reply and retries
once: with a "return only JSON" reminder after an unusable answer, or unchanged after a
timeout or connection error. After that the window falls back to keywords only.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from chaukas.core.config import LLMConfig
from chaukas.core.errors import LLMReplyError, LLMUnavailableError
from chaukas.llm.schema import LLMReply, parse_reply

Message = Mapping[str, str]
Transport = Callable[[str, Mapping[str, Any], float], Any]

RETRY_REMINDER: Final = (
    "That was not a valid answer. Return ONLY the JSON object described in the "
    "instructions, with no other text."
)


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    latency_s: float


class Chat(Protocol):
    def chat(self, messages: Sequence[Message]) -> ChatResult: ...


def http_transport(url: str, payload: Mapping[str, Any], timeout: float) -> Any:
    """POST ``payload`` as JSON and return the decoded JSON response."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LLMUnavailableError(f"LLM request to {url} failed: {exc}") from exc


class ChatClient:
    """One chat completion per call, timed with a monotonic clock."""

    __slots__ = ("_clock", "_max_tokens", "_model", "_temperature", "_timeout", "_transport",
                 "_url")  # fmt: skip

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_s: float,
        max_tokens: int,
        temperature: float,
        transport: Transport = http_transport,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._timeout = timeout_s
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._transport = transport
        self._clock = clock

    @classmethod
    def from_config(cls, config: LLMConfig, **kwargs: Any) -> ChatClient:
        return cls(
            base_url=config.base_url,
            model=config.model,
            timeout_s=config.timeout_s,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            **kwargs,
        )

    @property
    def model(self) -> str:
        return self._model

    def chat(self, messages: Sequence[Message]) -> ChatResult:
        payload = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }
        start = self._clock()
        try:
            response = self._transport(self._url, payload, self._timeout)
        except LLMUnavailableError as exc:
            raise LLMUnavailableError(str(exc), elapsed_s=self._clock() - start) from exc
        latency = self._clock() - start
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(f"unexpected response shape: {response!r:.200}") from exc
        if not isinstance(content, str):
            raise LLMUnavailableError("response has no text content")
        return ChatResult(content=content, latency_s=latency)


@dataclass(frozen=True, slots=True)
class LLMCall:
    """What one assessment attempt produced, successful or not."""

    reply: LLMReply | None
    latency_s: float  # every attempt, end to end
    attempts: int
    error: str | None
    raw: tuple[str, ...]  # raw completions, for evaluation logs (synthetic data only)


def assess(chat: Chat, system: str, user: str) -> LLMCall:
    """Ask once; retry once on an unusable answer or an unavailable server."""
    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    latency = 0.0
    raw: list[str] = []
    error = ""
    for attempt in (1, 2):
        try:
            result = chat.chat(messages)
        except LLMUnavailableError as exc:
            error = str(exc)
            latency += exc.elapsed_s
            continue
        latency += result.latency_s
        raw.append(result.content)
        try:
            reply = parse_reply(result.content)
        except LLMReplyError as exc:
            error = str(exc)
            messages = [
                *messages,
                {"role": "assistant", "content": result.content},
                {"role": "user", "content": RETRY_REMINDER},
            ]
            continue
        return LLMCall(reply=reply, latency_s=latency, attempts=attempt, error=None,
                       raw=tuple(raw))  # fmt: skip
    return LLMCall(reply=None, latency_s=latency, attempts=2, error=error, raw=tuple(raw))
