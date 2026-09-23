"""Live protection: real audio and the desktop monitor, feeding the window.

    loopback (caller) --+
                         +--> AudioPipeline --HeardLine--> bridge.post_line --+
    microphone (user) ---+                                                    +--> LiveSession
    desktop monitor + Downloads watcher --ContextEvent--> bridge.post_context --+

Audio starts on a background thread, because loading Whisper takes a few seconds and the
window should appear at once; progress and problems are reported with ``post_status``.
While the user has paused Chaukas, audio chunks are dropped before any processing, so
"not listening" is literally true. Everything here uses only the local machine.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import partial
from typing import Any

from chaukas.core.config import ChaukasConfig
from chaukas.core.errors import ChaukasError
from chaukas.core.models import Stream
from chaukas.ui.bridge import DashboardBridge

logger = logging.getLogger(__name__)


class _SessionClock:
    """The bridge's session time, as a Clock."""

    __slots__ = ("_now",)

    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now

    def now(self) -> float:
        return self._now()


class LiveServices:
    def __init__(
        self, bridge: DashboardBridge, config: ChaukasConfig, *, audio: bool, screen: bool
    ) -> None:
        self._bridge = bridge
        self._config = config
        self._want_audio = audio
        self._want_screen = screen
        self._stopping = threading.Event()
        self._audio_thread: threading.Thread | None = None
        self._system: Any = None
        self._pipeline: Any = None
        self._captures: list[Any] = []
        self._monitor: Any = None

    @property
    def audio_running(self) -> bool:
        return bool(self._captures)

    @property
    def screen_running(self) -> bool:
        return self._monitor is not None and self._monitor.running

    def start(self) -> None:
        self._stopping.clear()
        if self._want_screen:
            self._start_screen()
        if self._want_audio:
            self._audio_thread = threading.Thread(
                target=self._start_audio, name="chaukas-audio-start", daemon=True
            )
            self._audio_thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._audio_thread is not None:
            self._audio_thread.join(timeout=30)
            self._audio_thread = None
        self._stop_audio()
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    # ---------------------------------------------------------------- screen

    def _start_screen(self) -> None:
        from chaukas.context.downloads import DownloadClassifier, DownloadPoller
        from chaukas.context.monitor import ContextMonitor
        from chaukas.context.processes import ProcessWatcher, list_processes
        from chaukas.context.rules import ContextRules
        from chaukas.context.win32 import downloads_folder, foreground_window
        from chaukas.context.windows import WindowWatcher

        rules = ContextRules.load()
        clock = _SessionClock(self._bridge.session_time)
        self._monitor = ContextMonitor(
            clock=clock,
            publish=self._bridge.post_context,
            processes=ProcessWatcher(rules, list_processes),
            windows=WindowWatcher(rules),
            read_foreground=foreground_window,
            poll_s=1.0,
            downloads=DownloadPoller(downloads_folder(), DownloadClassifier(rules)),
        )
        self._monitor.start()

    # ----------------------------------------------------------------- audio

    def _start_audio(self) -> None:
        post = self._bridge.post_status
        post("Starting speech recognition…")
        try:
            from chaukas.asr.base import ModelMissingError
            from chaukas.asr.loader import load_transcriber
            from chaukas.audio.capture import AudioSystem
            from chaukas.audio.pipeline import AudioPipeline
            from chaukas.audio.vad import find_vad_model

            asr = self._config.asr
            transcriber = load_transcriber(asr)
            vad_model = find_vad_model()
            if vad_model is None:
                raise ModelMissingError("the voice detection model is missing; run: chaukas setup")
            if self._stopping.is_set():
                return
            self._system = AudioSystem()
            sources = [(Stream.CALLER, self._system.default_loopback()),
                       (Stream.USER, self._system.default_microphone())]  # fmt: skip
            found = [(stream, device) for stream, device in sources if device is not None]
            if not found:
                raise ChaukasError("no speaker output or microphone was found")
            self._pipeline = AudioPipeline(
                self._config.audio,
                vad_model=vad_model,
                transcriber=transcriber,
                on_line=self._bridge.post_line,
                clock=self._bridge.session_time,
                redetect_every=asr.redetect_every,
                merge_max_s=asr.merge_max_s,
            )
            for stream, device in found:
                self._pipeline.add_stream(stream, in_rate=device.rate, channels=device.channels)
            self._pipeline.start()
            for stream, device in found:
                capture = self._system.open(device, partial(self._on_chunk, stream),
                                            clock=self._bridge.session_time)  # fmt: skip
                capture.start()
                self._captures.append(capture)
            if self._stopping.is_set():
                return
            names = {stream: device.name for stream, device in found}
            post("Listening: caller = " + names.get(Stream.CALLER, "none")
                 + " · you = " + names.get(Stream.USER, "none"))  # fmt: skip
        except (ChaukasError, ImportError, OSError) as exc:
            logger.warning("live audio is unavailable: %s", exc)
            post(f"Audio unavailable: {exc}")
            self._stop_audio()

    def _on_chunk(self, stream: Stream, samples: Any, at: float) -> None:
        """PortAudio's thread: hand the chunk on, unless the user paused Chaukas."""
        if self._pipeline is not None and not self._bridge.paused:
            self._pipeline.feed(stream, samples, arrived=at)

    def _stop_audio(self) -> None:
        for capture in self._captures:
            try:
                capture.stop()
            except OSError as exc:
                logger.warning("stopping audio capture failed: %s", exc)
        self._captures = []
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
        if self._system is not None:
            self._system.close()
            self._system = None
