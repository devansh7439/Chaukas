"""Executables arriving in the Downloads folder (blueprint 6.5).

Browsers write ``.crdownload`` / ``.part`` files and rename them when the download
finishes, so both "created" and "moved" events are classified, by the final name. The
folder is the Downloads *known folder*, which OneDrive can redirect.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chaukas.context.rules import ContextRules
from chaukas.core.clock import Clock
from chaukas.core.models import ContextEvent, ContextKind

logger = logging.getLogger(__name__)


class DownloadClassifier:
    """Pure part: filesystem events in, at most one ContextEvent per finished file."""

    __slots__ = ("_rules", "_seen")

    def __init__(self, rules: ContextRules) -> None:
        self._rules = rules
        self._seen: set[str] = set()

    def created(self, now: float, path: Path) -> ContextEvent | None:
        return self._classify(now, path)

    def moved(self, now: float, source: Path, destination: Path) -> ContextEvent | None:
        del source
        return self._classify(now, destination)

    def _classify(self, now: float, path: Path) -> ContextEvent | None:
        if not self._rules.is_executable(path):
            return None
        key = str(path).casefold()
        if key in self._seen:
            return None
        self._seen.add(key)
        return ContextEvent(t=now, kind=ContextKind.DOWNLOAD_EXECUTABLE, detail=path.name)


class DownloadWatcher:
    """watchdog observer on one folder (the ``context`` extra). Not recursive."""

    def __init__(
        self,
        folder: Path,
        classifier: DownloadClassifier,
        clock: Clock,
        publish: Callable[[ContextEvent], None],
    ) -> None:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        watcher = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event: Any) -> None:
                if not event.is_directory:
                    watcher._emit(classifier.created(clock.now(), Path(event.src_path)))

            def on_moved(self, event: Any) -> None:
                if not event.is_directory:
                    watcher._emit(
                        classifier.moved(clock.now(), Path(event.src_path), Path(event.dest_path))
                    )

        self._publish = publish
        self._observer = Observer()
        self._observer.schedule(_Handler(), str(folder), recursive=False)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5.0)

    def _emit(self, event: ContextEvent | None) -> None:
        if event is not None:
            try:
                self._publish(event)
            except Exception:
                logger.exception("publishing a download event failed")
