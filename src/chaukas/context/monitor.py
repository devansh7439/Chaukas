"""The context monitor: polls processes, the foreground window and Downloads at 1 Hz (6.5).

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
from chaukas.context.processes import ProcessWatcher
from chaukas.context.windows import WindowWatcher
from chaukas.core.clock import Clock
from chaukas.core.models import ContextEvent

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
    ) -> None:
        if poll_s <= 0:
            raise ValueError(f"poll_s must be positive, got {poll_s}")
        self._clock = clock
        self._publish = publish
        self._processes = processes
        self._windows = windows
        self._read_foreground = read_foreground
        self._downloads = downloads
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
        for event in events:
            self._publish(event)

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

    def reset(self) -> None:
        """Session end: the next poll is a fresh baseline."""
        self._processes.reset()
        self._windows.reset()
        if self._downloads is not None:
            self._downloads.reset()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._poll_s)
