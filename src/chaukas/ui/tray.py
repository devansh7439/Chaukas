"""The notification-area (tray) icon while live protection runs.

A shield in the level's colour and a tooltip ("Chaukas: Warning") show the state at a
glance even when the window is minimised; the menu offers Open, Pause / Resume listening
and Quit. The alerts themselves stay the job of the alert windows.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QByteArray, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QWindow
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from chaukas.ui.bridge import DashboardBridge

ICONS: Final = Path(__file__).resolve().parent / "assets" / "icons"
_COLOURS: Final[Mapping[str, str]] = {
    "quiet": "#2F7D5B",
    "notice": "#C98A1B",
    "warning": "#E07B2E",
    "critical": "#C0392B",
    "critical_recovery": "#C0392B",
}


def tray_tooltip(view: Mapping[str, Any]) -> str:
    """ "Chaukas: Warning", with a note when listening is paused."""
    paused = " (paused: not listening)" if view.get("paused") else ""
    return f"Chaukas: {view.get('levelTitle', '')}{paused}"


def tray_icon(view: Mapping[str, Any]) -> tuple[str, str]:
    """The icon name and colour for the current level."""
    level = str(view.get("level", "quiet"))
    name = "shield-check" if level == "quiet" else "shield-alert"
    return name, _COLOURS.get(level, _COLOURS["quiet"])


def _render(name: str, colour: str, size: int = 64) -> QIcon:
    svg = (ICONS / f"{name}.svg").read_text(encoding="utf-8").replace("currentColor", colour)
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#F6F3EC"))
    painter.drawEllipse(QRectF(2, 2, size - 4, size - 4))
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(
        painter, QRectF(size * 0.17, size * 0.17, size * 0.66, size * 0.66)
    )
    painter.end()
    return QIcon(QPixmap.fromImage(image))


class Tray(QObject):
    """Mirrors the dashboard's level in the notification area."""

    def __init__(self, bridge: DashboardBridge, window: QWindow, app: QApplication) -> None:
        super().__init__(app)
        self._bridge = bridge
        self._window = window
        self._icon = QSystemTrayIcon(app)
        menu = QMenu()
        menu.addAction("Open Chaukas", self._open)
        self._pause = menu.addAction("Pause listening", self.toggle_pause)
        menu.addSeparator()
        menu.addAction("Quit Chaukas", app.quit)
        self._menu = menu  # the tray icon does not own its menu
        self._icon.setContextMenu(menu)
        self._icon.activated.connect(self._on_activated)
        bridge.viewChanged.connect(self.refresh)
        self.refresh()
        self._icon.show()

    def refresh(self) -> None:
        view: Mapping[str, Any] = self._bridge.property("view")
        self._icon.setToolTip(tray_tooltip(view))
        self._icon.setIcon(_render(*tray_icon(view)))
        self._pause.setText("Resume listening" if view.get("paused") else "Pause listening")

    def toggle_pause(self) -> None:
        self._bridge.togglePause()

    def tooltip(self) -> str:
        return self._icon.toolTip()

    def icon(self) -> QIcon:
        return self._icon.icon()

    def pause_label(self) -> str:
        return self._pause.text()

    def hide(self) -> None:
        self._icon.hide()

    def _open(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.requestActivate()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):  # fmt: skip
            self._open()
