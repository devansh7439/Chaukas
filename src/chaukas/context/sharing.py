"""Is the screen being shared? Windows records which apps capture it.

"Join the Meet link and share your screen" starts no remote-access tool: the browser tab
itself sends the screen, and the caller watches the user open their bank. Windows keeps a
per-app record of screen capture in the same privacy store as the microphone
(``context/calls.py``): Chrome, Edge, Teams and WhatsApp capture through Windows Graphics
Capture, and while they do, their record has a stop time of 0. On this PC, a Chrome screen
share showed exactly that, and a stop time once it ended.

A share that starts while protection runs is a ``SCREEN_SHARED`` event, once per share.
Shares already running when protection starts are the baseline (like remote tools running
before the call), screenshot tools don't count, and Chaukas's own capture (OCR, through
GDI) is not recorded here but excluded anyway. Unreadable records change nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection
from typing import Final

from chaukas.context.calls import Records, apps_in_use, own_executables, read_records
from chaukas.context.rules import ContextRules
from chaukas.core.models import ContextEvent, ContextKind

logger = logging.getLogger(__name__)

# Windows Graphics Capture: without the yellow border (Chrome, Edge, Teams, WhatsApp), and
# programmatic capture by Store apps
CAPABILITIES: Final = ("graphicsCaptureWithoutBorder", "graphicsCaptureProgrammatic")


def read_capture_records() -> dict[str, tuple[int, int]] | None:
    """Screen-capture records of this Windows user, or None where there are none."""
    merged: dict[str, tuple[int, int]] = {}
    found = False
    for capability in CAPABILITIES:
        records = read_records(capability)
        if records is not None:
            found = True
            merged.update(records)
    return merged if found else None


def app_name(app: str) -> str:
    """The app's short name: "chrome.exe" for a desktop app's path, "MSTeams" for a Store
    app's package name."""
    name = app.rsplit("\\", 1)[-1]
    return name if "\\" in app else name.split("_", 1)[0]


class ScreenShareWatcher:
    """Reports each screen share that starts while protection runs."""

    __slots__ = ("_exclude", "_read", "_rules", "_seen")

    def __init__(
        self,
        rules: ContextRules,
        *,
        read: Callable[[], Records | None] = read_capture_records,
        exclude: Collection[str] | None = None,
    ) -> None:
        self._rules = rules
        self._read = read
        self._exclude = own_executables() if exclude is None else exclude
        self._seen: set[tuple[str, int]] | None = None  # (app, start) of shares seen

    def poll(self, now: float) -> list[ContextEvent]:
        sharing = self._sharing()
        if sharing is None:
            return []
        if self._seen is None:  # the first good read is the baseline
            self._seen = set(sharing)
            return []
        new = sorted(sharing - self._seen)
        self._seen |= sharing
        return [ContextEvent(t=now, kind=ContextKind.SCREEN_SHARED, detail=app_name(app))
                for app, _ in new]  # fmt: skip

    def reset(self) -> None:
        """Session end: the next good read is a fresh baseline."""
        self._seen = None

    def _sharing(self) -> set[tuple[str, int]] | None:
        try:
            records = self._read()
        except OSError:
            logger.warning("the screen-capture records could not be read")
            return None
        if records is None:
            return None
        starts = {key.replace("#", "\\"): start for key, (start, _) in records.items()}
        return {(app, starts[app]) for app in apps_in_use(records, exclude=self._exclude)
                if not self._rules.is_screenshot_tool(app_name(app))}  # fmt: skip
