"""Executables arriving in the Downloads folder (blueprint 6.5).

The context monitor lists the folder once a second. Browsers write ``.crdownload`` /
``.part`` files and rename them when the download finishes, so a finished executable shows
up as a new name. Files present at the first look are the baseline and never reported.
The folder is the Downloads *known folder*, which OneDrive can redirect.

Polling (instead of a filesystem-events library) keeps this dependency-free, which matters
on Windows on ARM64, and costs one directory listing per second.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from chaukas.context.rules import ContextRules
from chaukas.core.models import ContextEvent, ContextKind

logger = logging.getLogger(__name__)


class DownloadClassifier:
    """Pure part: file names in, at most one ContextEvent per finished executable."""

    __slots__ = ("_rules", "_seen")

    def __init__(self, rules: ContextRules) -> None:
        self._rules = rules
        self._seen: set[str] = set()

    def created(self, now: float, path: Path) -> ContextEvent | None:
        return self._classify(now, path)

    def moved(self, now: float, source: Path, destination: Path) -> ContextEvent | None:
        del source
        return self._classify(now, destination)

    def remember(self, path: Path) -> None:
        """Mark ``path`` as already seen (the baseline)."""
        self._seen.add(str(path).casefold())

    def _classify(self, now: float, path: Path) -> ContextEvent | None:
        if not self._rules.is_executable(path):
            return None
        key = str(path).casefold()
        if key in self._seen:
            return None
        self._seen.add(key)
        return ContextEvent(t=now, kind=ContextKind.DOWNLOAD_EXECUTABLE, detail=path.name)


class DownloadPoller:
    """Lists one folder (not recursively) on each ``poll``; reports new executables."""

    __slots__ = ("_classifier", "_folder", "_known")

    def __init__(self, folder: Path, classifier: DownloadClassifier) -> None:
        self._folder = folder
        self._classifier = classifier
        self._known: set[str] | None = None

    def poll(self, now: float) -> list[ContextEvent]:
        try:
            with os.scandir(self._folder) as entries:
                names = {entry.name for entry in entries if entry.is_file()}
        except OSError:
            return []  # missing or unreadable folder: nothing to report
        known = self._known
        self._known = names
        if known is None:
            for name in names:
                self._classifier.remember(self._folder / name)
            return []
        events = []
        for name in sorted(names - known):
            event = self._classifier.created(now, self._folder / name)
            if event is not None:
                events.append(event)
        return events

    def reset(self) -> None:
        self._known = None
