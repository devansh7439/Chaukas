"""The managed local LLM server: download (hash-checked), command line, and lifecycle."""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

from chaukas.core.config import load_config
from chaukas.core.errors import ChaukasError
from chaukas.llm import server
from chaukas.llm.server import ServerProcess, llama_command, loopback_address

LLM = load_config().llm


def zipped(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class TestAddress:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("http://127.0.0.1:8080/v1", ("127.0.0.1", 8080)),
            ("http://localhost:9000/v1", ("127.0.0.1", 9000)),
        ],
    )
    def test_loopback_urls_are_accepted(self, url: str, expected: tuple[str, int]) -> None:
        assert loopback_address(url) == expected

    @pytest.mark.parametrize(
        "url", ["http://0.0.0.0:8080/v1", "http://192.168.1.5:8080/v1", "http://example.com/v1"]
    )
    def test_a_managed_server_never_listens_beyond_this_pc(self, url: str) -> None:
        with pytest.raises(ChaukasError, match=r"127\.0\.0\.1"):
            loopback_address(url)


class TestCommand:
    def test_binds_loopback_and_passes_the_model(self, tmp_path: Path) -> None:
        command = llama_command(tmp_path / "llama-server.exe", tmp_path / "m.gguf",
                                host="127.0.0.1", port=8080, threads=6, ctx_size=4096)  # fmt: skip
        assert command[0] == str(tmp_path / "llama-server.exe")
        assert command[command.index("--host") + 1] == "127.0.0.1"
        assert command[command.index("--port") + 1] == "8080"
        assert command[command.index("-m") + 1] == str(tmp_path / "m.gguf")
        assert command[command.index("-t") + 1] == "6"
        assert "--no-webui" in command


class TestDownload:
    def test_extracts_a_build_whose_hash_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = zipped({"llama-server.exe": b"MZ", "ggml.dll": b"dll"})
        monkeypatch.setitem(server.BUILDS, "TEST", ("t.zip", hashlib.sha256(archive).hexdigest()))
        path = server.download_server(tmp_path, machine="TEST", fetch=lambda url: archive)
        assert path == server.server_dir(tmp_path) / "llama-server.exe"
        assert path.read_bytes() == b"MZ"
        assert server.find_server(tmp_path) == path

    def test_refuses_a_build_with_the_wrong_hash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(server.BUILDS, "TEST", ("t.zip", "0" * 64))
        with pytest.raises(ChaukasError, match="SHA-256"):
            server.download_server(tmp_path, machine="TEST", fetch=lambda url: b"tampered")
        assert server.find_server(tmp_path) is None

    def test_refuses_an_archive_that_writes_outside_its_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = zipped({"../evil.exe": b"MZ", "llama-server.exe": b"MZ"})
        monkeypatch.setitem(server.BUILDS, "TEST", ("t.zip", hashlib.sha256(archive).hexdigest()))
        with pytest.raises(ChaukasError, match="outside"):
            server.download_server(tmp_path / "models", machine="TEST", fetch=lambda url: archive)
        assert not (tmp_path / "evil.exe").exists()

    def test_an_unsupported_machine_is_explained(self, tmp_path: Path) -> None:
        with pytest.raises(ChaukasError, match=r"no llama\.cpp build"):
            server.download_server(tmp_path, machine="MIPS", fetch=lambda url: b"")

    def test_pinned_builds_cover_x64_and_arm64(self) -> None:
        assert {"AMD64", "ARM64"} <= set(server.BUILDS)
        for name, sha in server.BUILDS.values():
            assert server.BUILD in name
            assert len(sha) == 64


HEALTH_SERVER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')
    def log_message(self, *args):
        pass

HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class TestServerProcess:
    def test_starts_waits_for_health_and_stops(self, tmp_path: Path) -> None:
        script = tmp_path / "health.py"
        script.write_text(HEALTH_SERVER, encoding="utf-8")
        port = free_port()
        process = ServerProcess([sys.executable, str(script), str(port)],
                                health_url=f"http://127.0.0.1:{port}/health",
                                log=tmp_path / "server.log")  # fmt: skip
        with process:
            assert process.running
        assert not process.running

    def test_a_server_that_exits_early_reports_its_log(self, tmp_path: Path) -> None:
        process = ServerProcess(
            [sys.executable, "-c", "import sys; print('model file is corrupt'); sys.exit(3)"],
            health_url=f"http://127.0.0.1:{free_port()}/health",
            log=tmp_path / "server.log",
        )
        with pytest.raises(ChaukasError, match="model file is corrupt"):
            process.start(timeout_s=10)
        assert not process.running

    def test_a_busy_port_is_refused_rather_than_shared(self, tmp_path: Path) -> None:
        script = tmp_path / "health.py"
        script.write_text(HEALTH_SERVER, encoding="utf-8")
        port = free_port()
        url = f"http://127.0.0.1:{port}/health"
        with ServerProcess([sys.executable, str(script), str(port)], health_url=url,
                           log=tmp_path / "a.log"):  # fmt: skip
            second = ServerProcess([sys.executable, "-c", "pass"], health_url=url,
                                   log=tmp_path / "b.log")  # fmt: skip
            with pytest.raises(ChaukasError, match="already"):
                second.start(timeout_s=5)


class TestManaged:
    def test_an_external_server_is_not_managed(self) -> None:
        external = LLM.model_copy(update={"server": "external"})
        assert server.managed_server(external) is None

    def test_a_missing_binary_says_how_to_get_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CHAUKAS_MODELS", str(tmp_path))
        managed = LLM.model_copy(update={"server": "managed"})
        with pytest.raises(ChaukasError, match="chaukas setup --llm"):
            server.managed_server(managed)
