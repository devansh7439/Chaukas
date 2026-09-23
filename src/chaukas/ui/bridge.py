"""The bridge between the live session and QML.

Ticks the session four times a second on real time (optionally sped up for demos),
turns its state into plain view data with the presenter, and exposes it as Qt
properties. Signals fire only when a value actually changed, so QML re-renders only what
moved. Every user action arrives here as a slot.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QWindow

from chaukas.core.models import Stream
from chaukas.engine.templates import ChainTemplate
from chaukas.ui.capture_exclusion import set_capture_excluded
from chaukas.ui.copy import Language, labels, text
from chaukas.ui.live import LiveSession
from chaukas.ui.presenter import history_bars, present, transcript_view
from chaukas.ui.settings import UserSettings, save_settings

TICK_MS: Final = 250
HISTORY_BARS: Final = 28
_WINDOWS: Final = (60, 300, 0)  # seconds; 0 = the whole call


class DashboardBridge(QObject):
    viewChanged = Signal()
    transcriptChanged = Signal()
    historyChanged = Signal()
    labelsChanged = Signal()
    settingsChanged = Signal()
    toast = Signal(str)

    def __init__(
        self,
        live: LiveSession,
        templates: Sequence[ChainTemplate],
        settings: UserSettings,
        settings_file: Path | None,
        *,
        speed: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._live = live
        self._templates = tuple(templates)
        self._settings = settings
        self._settings_file = settings_file
        self._speed = speed
        self._clock = clock
        self._origin = clock()
        self._window_s = _WINDOWS[0]
        self._view: dict[str, Any] = {}
        self._transcript: list[dict[str, Any]] = []
        self._history: dict[str, Any] = {}
        self._labels = labels(settings.language)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.tick)
        self._refresh()

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._origin = self._clock() - self._live.now / self._speed
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def tick(self) -> None:
        """Advance the session to the clock's current time (the timer calls this)."""
        self._live.advance((self._clock() - self._origin) * self._speed)
        self._refresh()

    def jump(self, t: float) -> None:
        """Advance the session straight to ``t`` (screenshots, tests, scrubbing)."""
        self._live.advance(t)
        self._origin = self._clock() - self._live.now / self._speed
        self._refresh()

    # ----------------------------------------------------------- properties

    def _get_view(self) -> dict[str, Any]:
        return self._view

    def _get_transcript(self) -> list[dict[str, Any]]:
        return self._transcript

    def _get_history(self) -> dict[str, Any]:
        return self._history

    def _get_labels(self) -> dict[str, str]:
        return self._labels

    def _get_language(self) -> str:
        return self._settings.language

    def _get_contact_name(self) -> str:
        return self._settings.contact_name

    def _get_contact_number(self) -> str:
        return self._settings.contact_number

    def _get_capture_exclusion(self) -> bool:
        return self._settings.capture_exclusion

    def _get_history_window(self) -> int:
        return self._window_s

    view = Property(dict, _get_view, notify=viewChanged)
    transcript = Property(list, _get_transcript, notify=transcriptChanged)
    history = Property(dict, _get_history, notify=historyChanged)
    labels = Property(dict, _get_labels, notify=labelsChanged)
    language = Property(str, _get_language, notify=settingsChanged)
    contactName = Property(str, _get_contact_name, notify=settingsChanged)
    contactNumber = Property(str, _get_contact_number, notify=settingsChanged)
    captureExclusion = Property(bool, _get_capture_exclusion, notify=settingsChanged)
    historyWindow = Property(int, _get_history_window, notify=historyChanged)

    # ---------------------------------------------------------------- slots

    @Slot(str, str)
    def say(self, line: str, speaker: str) -> None:
        stream = Stream.USER if speaker == "user" else Stream.CALLER
        if self._live.say(line, stream):
            self._refresh()

    @Slot()
    def togglePause(self) -> None:
        self._live.set_paused(not self._live.paused)
        self._refresh()

    @Slot()
    def endSession(self) -> None:
        self._live.end_session()
        self._refresh()
        self.toast.emit(text("wiped", self._settings.language))

    @Slot()
    def dismiss(self) -> None:
        self._live.dismiss()
        self._refresh()

    @Slot(str)
    def setLanguage(self, language: str) -> None:
        if language not in ("en", "hi") or language == self._settings.language:
            return
        chosen: Language = "hi" if language == "hi" else "en"
        self._update_settings(language=chosen)
        self._labels = labels(chosen)
        self.labelsChanged.emit()
        self._refresh()

    @Slot(int)
    def setHistoryWindow(self, seconds: int) -> None:
        if seconds in _WINDOWS and seconds != self._window_s:
            self._window_s = seconds
            self._refresh()

    @Slot(str, str)
    def saveContact(self, name: str, number: str) -> None:
        self._update_settings(contact_name=name, contact_number=number)
        self.toast.emit(text("settings_saved", self._settings.language))

    @Slot(bool)
    def setCaptureExclusion(self, excluded: bool) -> None:
        self._update_settings(capture_exclusion=excluded)

    @Slot(QObject)
    def protectWindow(self, window: QObject) -> None:
        """Called by alert windows when shown; applies capture exclusion if enabled."""
        if self._settings.capture_exclusion and isinstance(window, QWindow):
            set_capture_excluded(int(window.winId()), True)

    # -------------------------------------------------------------- helpers

    def _update_settings(self, **changes: Any) -> None:
        self._settings = replace(self._settings, **changes)
        if self._settings_file is not None:
            save_settings(self._settings, self._settings_file)
        self.settingsChanged.emit()

    def _refresh(self) -> None:
        language = self._settings.language
        view = present(
            self._live.state, templates=self._templates, language=language,
            paused=self._live.paused,
        )  # fmt: skip
        if view != self._view:
            self._view = view
            self.viewChanged.emit()
        transcript = transcript_view(self._live.transcript, language)
        if transcript != self._transcript:
            self._transcript = transcript
            self.transcriptChanged.emit()
        history = self._history_view()
        if history != self._history:
            self._history = history
            self.historyChanged.emit()

    def _history_view(self) -> dict[str, Any]:
        points = self._live.history
        now = self._live.now
        window = float(self._window_s) or max(now, 60.0)
        bars = history_bars(points, now=now, window_s=window, bars=HISTORY_BARS)
        peak = max((score for _, score in points), default=0.0)
        return {
            "bars": bars,
            "peakPercent": round(peak * 100),
            "window": self._window_s,
        }
