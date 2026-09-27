"""A local LLM server that Chaukas starts and stops itself (``llm.server: managed``).

The server is llama.cpp's ``llama-server``: one prebuilt binary with official Windows x64
and ARM64 builds and the OpenAI-compatible API the client already speaks, so no Python
package or native wheel is involved. ``chaukas setup --llm`` downloads the build pinned
below for this machine (SHA-256 checked, extracted without letting any entry escape its
folder) and the model file (pinned revision, SHA-256 checked).

A managed server only ever listens on 127.0.0.1: transcripts never leave the PC, and a
``base_url`` pointing anywhere else is refused. Each launch gets a new random API key
(passed through the environment, never the command line), so other processes and other
Windows users on the same PC cannot use it. If something already listens on the port,
Chaukas refuses to start rather than send transcripts to an unknown process.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import platform
import secrets
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Final, Self

from chaukas.core.config import LLMConfig
from chaukas.core.errors import ChaukasError
from chaukas.core.paths import models_dir

logger = logging.getLogger(__name__)

BUILD: Final = "b11218"
_RELEASE: Final = "https://github.com/ggml-org/llama.cpp/releases/download/" + BUILD + "/"
# machine (platform.machine()) -> (asset, SHA-256 published with the release)
BUILDS: Final[dict[str, tuple[str, str]]] = {
    "AMD64": (
        f"llama-{BUILD}-bin-win-cpu-x64.zip",
        "c5db5974ee132c4db6eafd4415238112b7af8350bc2f3882545121b515ef602b",
    ),
    "ARM64": (
        f"llama-{BUILD}-bin-win-cpu-arm64.zip",
        "38f4edd4200deaf53b1be9b5adcf741baada6dac8830e82af76042acae63a5a6",
    ),
}
BINARY: Final = "llama-server.exe"

# The default model: Qwen2.5-1.5B-Instruct, 4-bit, from Qwen's own repository.
GGUF_REPO: Final = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
GGUF_REVISION: Final = "91cad51170dc346986eccefdc2dd33a9da36ead9"
GGUF_SHA256: Final[Mapping[str, str]] = MappingProxyType(
    {"qwen2.5-1.5b-instruct-q4_k_m.gguf": (
        "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e")}
)  # fmt: skip

_LOOPBACK: Final = frozenset({"127.0.0.1", "localhost"})
_POLL_S: Final = 0.25


# ------------------------------------------------------------------ files


def server_dir(folder: Path | None = None) -> Path:
    return (folder if folder is not None else models_dir()) / "llama.cpp" / BUILD


def find_server(folder: Path | None = None) -> Path | None:
    path = server_dir(folder) / BINARY
    return path if path.is_file() else None


def download_server(
    folder: Path | None = None,
    *,
    machine: str | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> Path:
    """Fetch and unpack the pinned build for this machine; return the server binary."""
    machine = machine or platform.machine()
    if machine not in BUILDS:
        raise ChaukasError(f"there is no llama.cpp build for this machine ({machine})")
    asset, expected = BUILDS[machine]
    data = (fetch or _fetch)(_RELEASE + asset)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise ChaukasError(f"{asset}: SHA-256 is {digest}, expected {expected}; not installed")
    target = server_dir(folder)
    staging = target.with_name(target.name + ".part")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        _extract(data, staging)
        if not (staging / BINARY).is_file():
            raise ChaukasError(f"{asset} has no {BINARY}")
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target / BINARY


def _extract(data: bytes, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            path = (root / entry.filename).resolve()
            if not path.is_relative_to(root):
                raise ChaukasError(f"archive entry {entry.filename!r} points outside its folder")
        destination.mkdir(parents=True, exist_ok=True)
        archive.extractall(destination)


def find_gguf(name: str, folder: Path | None = None) -> Path | None:
    """``name`` as an absolute path, or in ``<models>/llm``."""
    path = Path(name)
    if not path.is_absolute():
        path = (folder if folder is not None else models_dir()) / "llm" / name
    return path if path.is_file() else None


def download_gguf(name: str, folder: Path | None = None) -> Path:
    """Fetch a pinned model file into ``<models>/llm`` and check its SHA-256."""
    if name not in GGUF_SHA256:
        raise ChaukasError(f"{name} is not a model Chaukas knows how to download; "
                           f"put it in {(folder or models_dir()) / 'llm'} yourself")  # fmt: skip
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import hf_hub_download

    target = (folder if folder is not None else models_dir()) / "llm"
    path = Path(hf_hub_download(GGUF_REPO, name, revision=GGUF_REVISION, local_dir=target))
    digest = _sha256_file(path)
    if digest != GGUF_SHA256[name]:
        path.unlink(missing_ok=True)
        raise ChaukasError(f"{name}: SHA-256 is {digest}, expected {GGUF_SHA256[name]}; deleted")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch(url: str) -> bytes:
    # Safe for bandit B310: url is the pinned https release URL, and the bytes are SHA-256 checked
    with urllib.request.urlopen(url, timeout=300) as response:  # nosec B310
        data: bytes = response.read()
    return data


# ---------------------------------------------------------------- process


def loopback_address(base_url: str) -> tuple[str, int]:
    """(host, port) for a managed server; refuses anything but this PC."""
    parts = urllib.parse.urlsplit(base_url)
    if parts.hostname not in _LOOPBACK:
        raise ChaukasError(
            f"a managed LLM server only listens on 127.0.0.1, but llm.base_url is {base_url}; "
            "use llm.server: external for a server elsewhere"
        )
    return "127.0.0.1", parts.port or 80


def llama_command(
    binary: Path, model: Path, *, host: str, port: int, threads: int, ctx_size: int
) -> list[str]:
    return [
        str(binary),
        "-m", str(model),
        "--host", host,
        "--port", str(port),
        "-t", str(threads),
        "-c", str(ctx_size),
        "-np", "1",  # one request at a time: the trigger policy never overlaps calls
        "--no-webui",
    ]  # fmt: skip


class ServerProcess:
    """A child process serving HTTP, ready once ``health_url`` answers 200."""

    __slots__ = ("_api_key", "_command", "_environment", "_health_url", "_log", "_log_handle",
                 "_process")  # fmt: skip

    def __init__(
        self,
        command: Sequence[str],
        *,
        health_url: str,
        log: Path,
        environment: Mapping[str, str] | None = None,
        api_key: str = "",
    ) -> None:
        self._command = list(command)
        self._health_url = health_url
        self._log = log
        self._environment = dict(environment or {})
        self._api_key = api_key
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle: io.BufferedWriter | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def command(self) -> tuple[str, ...]:
        return tuple(self._command)

    @property
    def environment(self) -> Mapping[str, str]:
        """Variables added to the child's environment (the API key travels here)."""
        return MappingProxyType(self._environment)

    @property
    def api_key(self) -> str:
        """The key requests must carry; empty if the server takes none."""
        return self._api_key

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def start(self, timeout_s: float) -> None:
        parts = urllib.parse.urlsplit(self._health_url)
        if _port_open(parts.hostname or "127.0.0.1", parts.port or 80):
            raise ChaukasError(
                f"something is already listening at {parts.netloc}; stop it, or set "
                "llm.server: external to use it"
            )
        self._log.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self._log.open("wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            self._command, stdin=subprocess.DEVNULL, stdout=self._log_handle,
            stderr=subprocess.STDOUT, creationflags=flags,
            env={**os.environ, **self._environment},
        )  # fmt: skip
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                tail = self._log_tail()
                self.stop()
                raise ChaukasError(f"the LLM server exited during start-up:\n{tail}")
            if _healthy(self._health_url):
                logger.info("LLM server ready at %s", parts.netloc)
                return
            time.sleep(_POLL_S)
        self.stop()
        raise ChaukasError(f"the LLM server was not ready after {timeout_s:.0f} s")

    def stop(self, timeout_s: float = 10.0) -> None:
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout_s)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def __enter__(self) -> Self:
        if not self.running:
            self.start(timeout_s=120.0)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    def _log_tail(self, lines: int = 12) -> str:
        if self._log_handle is not None:
            self._log_handle.flush()
        try:
            text = self._log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(no log)"
        return "\n".join(text.strip().splitlines()[-lines:])


def managed_server(config: LLMConfig) -> ServerProcess | None:
    """The server to start for ``config``, not yet started; None for an external server."""
    if config.server == "external":
        return None
    host, port = loopback_address(config.base_url)
    binary = find_server()
    if binary is None:
        raise ChaukasError("the local LLM server is not installed; run: chaukas setup --llm")
    model = find_gguf(config.gguf)
    if model is None:
        raise ChaukasError(f"the model {config.gguf} is not on this PC; run: chaukas setup --llm")
    command = llama_command(binary, model, host=host, port=port, threads=config.threads,
                            ctx_size=config.ctx_size)  # fmt: skip
    # A fresh 256-bit key per launch, so no other process or user on this PC can use the
    # server. It goes through the environment: a command line is visible in process lists.
    api_key = secrets.token_urlsafe(32)
    return ServerProcess(command, health_url=f"http://{host}:{port}/health",
                         log=server_dir() / "server.log",
                         environment={"LLAMA_API_KEY": api_key}, api_key=api_key)  # fmt: skip


def _healthy(url: str) -> bool:
    try:
        # Safe for bandit B310: url is http://127.0.0.1:<port>/health, built by this module
        with urllib.request.urlopen(url, timeout=2) as response:  # nosec B310
            return bool(response.status == 200)
    except (urllib.error.URLError, OSError, ValueError):
        return False  # not listening yet, or 503 while the model loads


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0
