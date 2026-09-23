"""Foreground window: window changes, and bank / transfer / OTP pages by title (6.5).

Titles only; Chaukas never reads URLs or page contents here. A classified title is
reported when it first appears, including when the user navigates inside one browser
window (the title changes, the window handle doesn't).
"""

from __future__ import annotations

from chaukas.context.rules import ContextRules
from chaukas.core.models import ContextEvent, ContextKind


class WindowWatcher:
    __slots__ = ("_hwnd", "_rules", "_title")

    def __init__(self, rules: ContextRules) -> None:
        self._rules = rules
        self._hwnd: int | None = None
        self._title: str | None = None

    def observe(self, now: float, hwnd: int | None, title: str) -> list[ContextEvent]:
        if hwnd is None:
            return []
        events: list[ContextEvent] = []
        if self._hwnd is not None and hwnd != self._hwnd:
            events.append(ContextEvent(t=now, kind=ContextKind.WINDOW_CHANGED, detail=title))
        self._hwnd = hwnd
        if title != self._title:
            self._title = title
            kind = self._rules.classify_title(title)
            if kind is not None:
                events.append(ContextEvent(t=now, kind=kind, detail=title))
        return events

    def reset(self) -> None:
        self._hwnd = None
        self._title = None
