"""The context monitor: polls processes, the foreground window, Downloads, screen sharing,
call presence and (while a call is suspicious) the active window's text, at 1 Hz (6.5).

Runs on its own daemon thread and publishes ContextEvents stamped with session time. A
reader that fails (access denied, a window closing mid-read) is logged and skipped for
that poll; it never stops the monitor.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Self

from chaukas.context.downloads import DownloadPoller
from chaukas.context.ocr import TriggeredOcr
from chaukas.context.processes import ProcessWatcher
from chaukas.context.sharing import ScreenShareWatcher
from chaukas.context.windows import WindowWatcher
from chaukas.core.clock import Clock
from chaukas.core.models import ContextEvent, ContextKind

logger = logging.getLogger(__name__)

ForegroundReader = Callable[[], tuple[int, str] | None]


class ContextMonitor:
    def __init__(
        self,
        *,
        clock: Clock,
        publish: Callable[[ContextEvent], None],
        processes: ProcessWatcher,
        windows: WindowWatcher,
        read_foreground: ForegroundReader,
        poll_s: float,
        downloads: DownloadPoller | None = None,
        screen: TriggeredOcr | None = None,
        calls: Callable[[], bool | None] | None = None,
        sharing: ScreenShareWatcher | None = None,
    ) -> None:
        if poll_s <= 0:
            raise ValueError(f"poll_s must be positive, got {poll_s}")
        self._clock = clock
        self._publish = publish
        self._processes = processes
        self._windows = windows
        self._read_foreground = read_foreground
        self._downloads = downloads
        self._screen = screen
        self._calls = calls  # call presence: True, False or None (unknown)
        self._call: bool | None = None
        self._sharing = sharing
        self._poll_s = poll_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def poll_once(self) -> None:
        now = self._clock.now()
        events: list[ContextEvent] = []
        try:
            events.extend(self._processes.poll(now))
        except Exception:
            logger.exception("process poll failed")
        try:
            foreground = self._read_foreground()
            if foreground is not None:
                events.extend(self._windows.observe(now, *foreground))
        except Exception:
            logger.exception("foreground window poll failed")
        if self._downloads is not None:
            try:
                events.extend(self._downloads.poll(now))
            except Exception:
                logger.exception("Downloads folder poll failed")
        if self._sharing is not None:
            try:
                events.extend(self._sharing.poll(now))
            except Exception:
                logger.exception("screen sharing check failed")
        if self._screen is not None:
            try:
                events.extend(self._screen.poll(now))
            except Exception:  # OCR unavailable or failed: titles and processes still work
                logger.exception("screen reading failed")
        if self._calls is not None:
            try:
                events.extend(self._call_change(now))
            except Exception:
                logger.exception("call presence check failed")
        for event in events:
            self._publish(event)

    def _call_change(self, now: float) -> list[ContextEvent]:
        """An event when the call state becomes known or changes; unknown is not news."""
        assert self._calls is not None
        state = self._calls()
        if state is None or state == self._call:
            return []
        self._call = state
        kind = ContextKind.CALL_ACTIVE if state else ContextKind.NO_CALL
        detail = "an app is using the microphone" if state else "no app is using the microphone"
        return [ContextEvent(t=now, kind=kind, detail=detail)]

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="chaukas-context", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        if self._screen is not None:
            self._screen.close()

    def reset(self) -> None:
        """Session end: the next poll is a fresh baseline."""
        self._call = None
        self._processes.reset()
        self._windows.reset()
        if self._downloads is not None:
            self._downloads.reset()
        if self._sharing is not None:
            self._sharing.reset()
        if self._screen is not None:
            self._screen.reset()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._poll_s)
