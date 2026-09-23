"""The OpenAI-compatible chat client, the retry policy, and the response cache."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from chaukas.core.errors import LLMUnavailableError
from chaukas.llm.cache import CachedChat
from chaukas.llm.client import RETRY_REMINDER, ChatClient, ChatResult, assess, http_transport

VALID = json.dumps({"addressed_to_user": True, "suspected_objective": "unclear", "tactics": []})


class FakeChat:
    """Returns scripted contents in order; records every message list it was sent."""

    def __init__(self, *contents: str | Exception, latency_s: float = 0.5) -> None:
        self._contents = list(contents)
        self.latency_s = latency_s
        self.sent: list[list[Mapping[str, str]]] = []

    def chat(self, messages: Sequence[Mapping[str, str]]) -> ChatResult:
        self.sent.append(list(messages))
        content = self._contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return ChatResult(content=content, latency_s=self.latency_s)


class TestAssess:
    def test_a_valid_first_answer(self) -> None:
        call = assess(FakeChat(VALID), "system", "user")
        assert call.reply is not None
        assert call.attempts == 1
        assert call.latency_s == 0.5
        assert call.error is None

    def test_invalid_json_is_retried_once_with_a_reminder(self) -> None:
        chat = FakeChat("Sure! The caller is a scammer.", VALID)
        call = assess(chat, "system", "user")
        assert call.reply is not None
        assert call.attempts == 2
        assert call.latency_s == 1.0  # both attempts count
        retry = chat.sent[1]
        assert retry[-2] == {"role": "assistant", "content": "Sure! The caller is a scammer."}
        assert retry[-1] == {"role": "user", "content": RETRY_REMINDER}

    def test_gives_up_after_the_second_failure(self) -> None:
        call = assess(FakeChat("nope", "still nope"), "system", "user")
        assert call.reply is None
        assert call.attempts == 2
        assert call.error is not None
        assert call.raw == ("nope", "still nope")

    def test_an_unreachable_server_is_retried_then_reported(self) -> None:
        down = LLMUnavailableError("connection refused")
        call = assess(FakeChat(down, down), "system", "user")
        assert call.reply is None
        assert call.error is not None
        assert "connection refused" in call.error

    def test_a_timeout_then_success(self) -> None:
        timeout = LLMUnavailableError("timed out", elapsed_s=10.0)
        call = assess(FakeChat(timeout, VALID), "system", "user")
        assert call.reply is not None
        assert call.attempts == 2
        assert call.latency_s == 10.5  # the time lost waiting counts too


class TestChatClient:
    def test_sends_an_openai_style_request(self) -> None:
        seen: dict[str, Any] = {}

        def transport(url: str, payload: Mapping[str, Any], timeout: float) -> Any:
            seen.update(url=url, payload=payload, timeout=timeout)
            return {"choices": [{"message": {"role": "assistant", "content": VALID}}]}

        ticks = iter([10.0, 12.5])
        client = ChatClient(
            base_url="http://127.0.0.1:8080/v1/",
            model="llama",
            timeout_s=10.0,
            max_tokens=300,
            temperature=0.0,
            transport=transport,
            clock=lambda: next(ticks),
        )
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == ChatResult(content=VALID, latency_s=2.5)
        assert seen["url"] == "http://127.0.0.1:8080/v1/chat/completions"
        assert seen["timeout"] == 10.0
        assert seen["payload"] == {
            "model": "llama",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.0,
            "max_tokens": 300,
            "stream": False,
        }

    def test_a_failed_request_reports_the_time_it_took(self) -> None:
        def transport(url: str, payload: Mapping[str, Any], timeout: float) -> Any:
            raise LLMUnavailableError("timed out")

        ticks = iter([0.0, 10.0])
        client = ChatClient(
            base_url="http://x/v1", model="m", timeout_s=10.0, max_tokens=10, temperature=0.0,
            transport=transport, clock=lambda: next(ticks),
        )  # fmt: skip
        with pytest.raises(LLMUnavailableError) as failure:
            client.chat([{"role": "user", "content": "hi"}])
        assert failure.value.elapsed_s == 10.0

    @pytest.mark.parametrize("response", [{}, {"choices": []}, {"choices": [{"message": {}}]}])
    def test_an_unexpected_response_shape_is_unavailable(self, response: Any) -> None:
        client = ChatClient(
            base_url="http://x/v1", model="m", timeout_s=1.0, max_tokens=10, temperature=0.0,
            transport=lambda url, payload, timeout: response,
        )  # fmt: skip
        with pytest.raises(LLMUnavailableError):
            client.chat([{"role": "user", "content": "hi"}])


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/fail"):
            self.send_response(500)
            self.end_headers()
            return
        reply = {"choices": [{"message": {"content": body["messages"][-1]["content"].upper()}}]}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


class TestHttpTransport:
    def test_round_trip_against_a_local_server(self, server: str) -> None:
        payload = {"messages": [{"role": "user", "content": "namaste"}]}
        response = http_transport(f"{server}/v1/chat/completions", payload, 5.0)
        assert response["choices"][0]["message"]["content"] == "NAMASTE"

    def test_http_errors_are_unavailable(self, server: str) -> None:
        with pytest.raises(LLMUnavailableError):
            http_transport(f"{server}/fail", {"messages": []}, 5.0)

    def test_a_closed_port_is_unavailable(self) -> None:
        with pytest.raises(LLMUnavailableError):
            http_transport("http://127.0.0.1:9/v1/chat/completions", {}, 0.5)


class TestCachedChat:
    def test_a_cached_answer_is_replayed_with_its_measured_latency(self, tmp_path: Path) -> None:
        inner = FakeChat(VALID, latency_s=3.2)
        cached = CachedChat(inner, tmp_path, model="m")
        messages = [{"role": "user", "content": "hi"}]
        first = cached.chat(messages)
        second = CachedChat(FakeChat(), tmp_path, model="m").chat(messages)
        assert first == second == ChatResult(content=VALID, latency_s=3.2)
        assert len(inner.sent) == 1

    def test_the_key_depends_on_model_and_messages(self, tmp_path: Path) -> None:
        cached = CachedChat(FakeChat(VALID, VALID, VALID), tmp_path, model="m")
        cached.chat([{"role": "user", "content": "a"}])
        cached.chat([{"role": "user", "content": "b"}])
        CachedChat(FakeChat(VALID), tmp_path, model="other").chat(
            [{"role": "user", "content": "a"}]
        )
        assert len(list(tmp_path.glob("*.json"))) == 3

    def test_offline_mode_refuses_to_call_the_model(self, tmp_path: Path) -> None:
        cached = CachedChat(FakeChat(VALID), tmp_path, model="m", offline=True)
        with pytest.raises(LLMUnavailableError, match="not in the cache"):
            cached.chat([{"role": "user", "content": "hi"}])

    def test_failures_are_not_cached(self, tmp_path: Path) -> None:
        cached = CachedChat(FakeChat(LLMUnavailableError("down"), VALID), tmp_path, model="m")
        messages = [{"role": "user", "content": "hi"}]
        with pytest.raises(LLMUnavailableError):
            cached.chat(messages)
        assert cached.chat(messages).content == VALID
