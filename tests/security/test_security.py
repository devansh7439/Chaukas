"""Security checks across Chaukas, in one place.

Chaukas has no database, user accounts or web API. Its attack surface is:
- text it does not control: the caller's words, window titles, file names, device names;
- data it must not leak: transcripts, codes read out, the trusted contact;
- things it downloads (models, the LLM server binary);
- the one network service it can start: the optional local LLM server.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from chaukas.core.config import load_config
from chaukas.core.errors import ConfigError

ROOT = Path(__file__).resolve().parents[2]
QML = ROOT / "src" / "chaukas" / "ui" / "qml"


# ------------------------------------------------------ untrusted text in the window


class TestUntrustedTextIsNeverMarkup:
    """A web page controls its own title; the caller controls their words. Qt's Text
    defaults to AutoText, which renders anything that looks like HTML as HTML."""

    def test_every_text_element_is_the_plain_text_component(self) -> None:
        offenders = []
        for path in QML.glob("*.qml"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                is_text = re.match(r"\s*(Text|Label|TextEdit|TextArea)\s*\{", line)
                if is_text and path.name != "AppText.qml":
                    offenders.append(f"{path.name}:{number}")
        assert offenders == []

    def test_the_text_component_forces_plain_text(self) -> None:
        source = (QML / "AppText.qml").read_text(encoding="utf-8")
        assert "textFormat: Text.PlainText" in source
        assert "RichText" not in source
        assert "StyledText" not in source

    def test_no_qml_file_asks_for_rich_text(self) -> None:
        for path in QML.glob("*.qml"):
            source = path.read_text(encoding="utf-8")
            assert "Text.RichText" not in source, path.name
            assert "Text.StyledText" not in source, path.name
            assert "Text.MarkdownText" not in source, path.name


# ------------------------------------------------------------- files it reads


class TestFilesCannotRunCode:
    def test_yaml_tags_that_would_run_python_are_rejected(self, tmp_path: Path) -> None:
        evil = tmp_path / "evil.yaml"
        evil.write_text("signals: !!python/object/apply:os.system ['echo pwned']\n",
                        encoding="utf-8")  # fmt: skip
        with pytest.raises(ConfigError):
            load_config(evil)

    def test_a_case_file_cannot_run_python_either(self, tmp_path: Path) -> None:
        from chaukas.evaluation.cases import load_case

        evil = tmp_path / "X.yaml"
        evil.write_text("case_id: !!python/object/apply:os.getcwd []\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_case(evil)


class TestLLMEndpoint:
    @pytest.mark.parametrize("url", ["file:///C:/Windows/win.ini", "ftp://example.com/v1",
                                     "javascript:alert(1)"])  # fmt: skip
    def test_only_http_urls_are_accepted(self, url: str) -> None:
        with pytest.raises(ConfigError, match="http"):
            load_config({"llm": {"base_url": url}})

    def test_the_default_endpoint_is_this_pc(self) -> None:
        assert load_config().llm.base_url.startswith("http://127.0.0.1:")


# ---------------------------------------------------------- downloads are pinned


class TestDownloadsArePinned:
    def test_the_whisper_model_is_pinned_to_a_revision(self) -> None:
        from chaukas.asr import whisper_onnx

        assert re.fullmatch(r"[0-9a-f]{40}", whisper_onnx.REVISION)

    def test_every_other_download_is_hash_checked(self) -> None:
        from chaukas.audio import vad
        from chaukas.llm import server

        assert re.fullmatch(r"[0-9a-f]{64}", vad.MODEL_SHA256)
        assert all(re.fullmatch(r"[0-9a-f]{64}", sha) for _, sha in server.BUILDS.values())
        assert all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in server.GGUF_SHA256.values())
        assert re.fullmatch(r"[0-9a-f]{40}", server.GGUF_REVISION)


# ------------------------------------------------------ transcripts never logged


class TestNoTranscriptInLogs:
    SECRET = "mera OTP 4 7 2 9 1 5 hai aur contact Maa 9876543210"

    def test_the_audio_pipeline_logs_no_speech_even_at_debug(
        self, caplog: pytest.LogCaptureFixture, speech: Any
    ) -> None:
        np = pytest.importorskip("numpy")
        pytest.importorskip("onnxruntime")
        from chaukas.asr.base import Transcript
        from chaukas.audio.pipeline import AudioPipeline
        from chaukas.audio.vad import find_vad_model
        from chaukas.core.models import Stream

        model = find_vad_model()
        if model is None:
            pytest.skip("no voice detection model")

        class Echoing:
            def transcribe(self, samples: Any, *, language: str | None = None) -> Transcript:
                return Transcript(text=TestNoTranscriptInLogs.SECRET, language="hi", ms=1.0)

        heard: list[Any] = []
        pipeline = AudioPipeline(load_config().audio, vad_model=model, transcriber=Echoing(),
                                 on_line=heard.append)  # fmt: skip
        pipeline.add_stream(Stream.CALLER, in_rate=16_000, channels=1)
        pipeline.add_stream(Stream.USER, in_rate=16_000, channels=1)
        audio = np.concatenate([speech("Tell me the code."), np.zeros(16_000, np.float32)])
        with caplog.at_level(logging.DEBUG):
            pipeline.start()
            try:
                for i in range(0, len(audio), 1600):
                    pipeline.feed(Stream.CALLER, audio[i : i + 1600], arrived=(i + 1600) / 16e3)
                    pipeline.feed(Stream.USER, audio[i : i + 1600], arrived=(i + 1600) / 16e3)
                assert pipeline.drain(20.0)
            finally:
                pipeline.stop()
        assert heard  # the text did flow through the pipeline...
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "OTP" not in logged  # ...but never into a log message
        assert "9876543210" not in logged

    def test_the_whisper_loop_guard_logs_no_text(self) -> None:
        source = (ROOT / "src" / "chaukas" / "asr" / "whisper_onnx.py").read_text(encoding="utf-8")
        for call in re.findall(r"logger\.\w+\((.*?)\)\n", source, flags=re.S):
            arguments = [arg.strip() for arg in call.split(",")[1:]]
            # the text itself (or a slice of it) must never be an argument; its length may
            assert not any(re.match(r"text\b(?!\))", arg) for arg in arguments), call


# ------------------------------------------------ the one service Chaukas starts


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class TestManagedServerAccess:
    def test_each_launch_gets_a_new_random_key_outside_the_command_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from chaukas.llm import server

        monkeypatch.setenv("CHAUKAS_MODELS", str(tmp_path))
        server.server_dir(tmp_path).mkdir(parents=True)
        (server.server_dir(tmp_path) / server.BINARY).write_bytes(b"MZ")
        (tmp_path / "llm").mkdir()
        (tmp_path / "llm" / "m.gguf").write_bytes(b"gguf")
        llm = load_config().llm.model_copy(update={"server": "managed", "gguf": "m.gguf"})
        first, second = server.managed_server(llm), server.managed_server(llm)
        assert first is not None
        assert second is not None
        assert len(first.api_key) >= 32
        assert first.api_key != second.api_key
        assert first.api_key not in " ".join(first.command)  # never visible in a process list
        assert first.environment["LLAMA_API_KEY"] == first.api_key

    def test_the_client_sends_its_key(self) -> None:
        from chaukas.llm.client import http_transport

        seen: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                seen["auth"] = self.headers.get("Authorization", "")
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: Any) -> None:
                pass

        httpd = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/v1/chat/completions"
            http_transport(url, {}, 5.0, api_key="s3cret-key")
        finally:
            httpd.shutdown()
            httpd.server_close()
        assert seen["auth"] == "Bearer s3cret-key"

    def test_the_real_server_listens_on_loopback_only_and_refuses_requests_without_the_key(
        self,
    ) -> None:
        psutil = pytest.importorskip("psutil")
        from chaukas.llm import server

        llm = load_config().llm
        if server.find_server() is None or server.find_gguf(llm.gguf) is None:
            pytest.skip("the managed LLM server is not installed (chaukas setup --llm)")
        port = _free_port()
        process = server.managed_server(
            llm.model_copy(update={"base_url": f"http://127.0.0.1:{port}/v1", "threads": 2})
        )
        assert process is not None
        with process:
            pid = process.pid
            assert pid is not None
            listening = {
                conn.laddr.ip
                for conn in psutil.Process(pid).net_connections(kind="inet")
                if conn.status == psutil.CONN_LISTEN
            }
            assert listening == {"127.0.0.1"}
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=b'{"messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}',
                headers={"Content-Type": "application/json"},
            )
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(request, timeout=30)
            refused.value.close()  # the error holds the response's socket
            assert refused.value.code == 401
            request.add_header("Authorization", f"Bearer {process.api_key}")
            with urllib.request.urlopen(request, timeout=60) as answer:
                assert answer.status == 200


class TestNothingListensDuringLiveProtection:
    def test_the_screen_monitor_opens_no_listening_socket(self, tmp_path: Path) -> None:
        psutil = pytest.importorskip("psutil")
        pytest.importorskip("PySide6")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from chaukas.ui.app import create_app, load_ui
        from chaukas.ui.services import LiveServices

        def listening() -> set[tuple[str, int]]:
            # this whole test process; other tests' fake servers may already be open here
            return {(c.laddr.ip, c.laddr.port) for c in psutil.Process().net_connections("inet")
                    if c.status == psutil.CONN_LISTEN}  # fmt: skip

        create_app(headless=True)
        before = listening()
        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True)
        services = LiveServices(ui.bridge, ui.config, audio=False, screen=True)
        services.start()
        try:
            time.sleep(1.5)  # a monitor poll or two
            opened = listening() - before
        finally:
            services.stop()
            ui.close()
        assert opened == set()


# ------------------------------------------------------------- the repository


class TestRepository:
    def test_secrets_and_local_data_are_git_ignored(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".env", "models/", "eval/cache/", "*.wav"):
            assert pattern in ignored, pattern


# ------------------------------------ caller speech can't switch off a safety signal


def _credential_request_in(text: str) -> bool:
    from chaukas.core.models import Segment, SignalKind, Stream
    from chaukas.signals.extractor import SignalExtractor
    from chaukas.signals.lexicon import Lexicon

    extractor = SignalExtractor(Lexicon.load(), load_config().signals)
    segment = Segment(session_id="s", seg_id=0, stream=Stream.CALLER, t_start=0.0, t_end=3.0,
                      text=text)  # fmt: skip
    return any(s.kind is SignalKind.CREDENTIAL_REQUEST for s in extractor.extract(segment))


class TestCallerCannotSuppressTheOtpRequest:
    """The caller is an untrusted source. Protective-sounding words ("don't tell anyone")
    must not turn a request aimed at the caller into harmless advice."""

    @pytest.mark.parametrize(
        "line",
        [
            "Kisi ko OTP mat batana, sirf mujhe batao.",
            "Never share your OTP with anyone else, just read it out to me.",
            "OTP kisi aur ko mat dena, mujhe bata dijiye.",
            "Bank kabhi OTP nahi maangta, lekin verification ke liye abhi OTP batao.",
            "Don't share the OTP with anyone except me. Tell me the OTP now.",
            "Ignore the warning on your screen, that software is fake. Tell me the OTP.",
        ],
    )
    def test_a_request_hidden_behind_advice_is_still_a_request(self, line: str) -> None:
        assert _credential_request_in(line)

    @pytest.mark.parametrize(
        "line",
        [
            "Bank kabhi OTP ya PIN nahi maangta, kisi ko mat bataiye.",
            "We will never ask for your OTP. Please do not share it with anyone.",
            "Please OTP mujhe mat bataiye, sirf app mein type kijiye.",
            "Never share your OTP or PIN with anyone, not even with bank staff.",
            "Never share your OTP. If anyone asks for it, tell us.",
        ],
    )
    def test_genuine_advice_is_still_advice(self, line: str) -> None:
        assert not _credential_request_in(line)

    def test_after_an_authority_claim_the_redirect_is_critical_before_any_answer(self) -> None:
        from chaukas.core.models import Level, Segment, Stream
        from chaukas.engine.risk import RiskEngine
        from chaukas.evaluation.ablation import config_for
        from chaukas.evaluation.session import Session
        from chaukas.signals.extractor import SignalExtractor
        from chaukas.signals.lexicon import Lexicon

        config = config_for("E")
        session = Session(SignalExtractor(Lexicon.load(), config.signals),
                          RiskEngine.from_config(config))  # fmt: skip
        for i, text in enumerate(["Main SBI bank se bol raha hoon.",
                                  "Kisi ko OTP mat batana, sirf mujhe batao."]):  # fmt: skip
            start = 4.0 * i
            session.feed_segment(Segment(session_id="s", seg_id=i, stream=Stream.CALLER,
                                         t_start=start, t_end=start + 3.0, text=text))  # fmt: skip
        assert session.evaluate(10.0).state.level is Level.CRITICAL
