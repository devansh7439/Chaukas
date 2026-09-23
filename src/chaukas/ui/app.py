"""Start the Chaukas window: fonts, icon provider, the bridge and the QML scene.

``run`` is the interactive entry point (``chaukas ui``). ``load_ui`` builds everything
without entering the event loop, for tests and for ``--screenshot``, which renders
headless with the software renderer and saves one PNG per visible window.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonType
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

from chaukas.core.errors import ChaukasError
from chaukas.engine.templates import load_templates
from chaukas.evaluation.ablation import config_for
from chaukas.evaluation.cases import load_case
from chaukas.signals.lexicon import Lexicon
from chaukas.ui.bridge import DashboardBridge
from chaukas.ui.icons import IconProvider
from chaukas.ui.live import LiveSession
from chaukas.ui.settings import load_settings, settings_path

HERE: Final = Path(__file__).resolve().parent
ASSETS: Final = HERE / "assets"
QML_DIR: Final = HERE / "qml"
FONT_FAMILY: Final = "Plus Jakarta Sans"
DEVANAGARI_FAMILY: Final = "Noto Sans Devanagari"
ALERT_WINDOWS: Final = ("noticeWindow", "warningWindow", "criticalWindow")

_registered = False


def create_app(*, headless: bool) -> QGuiApplication:
    """The application object (created once), with the bundled fonts loaded."""
    global _registered
    existing = QGuiApplication.instance()
    if isinstance(existing, QGuiApplication):
        return existing
    if headless:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        # The offscreen platform has no system fonts: use only the bundled ones.
        os.environ.setdefault("QT_QPA_FONTDIR", str(ASSETS / "fonts"))
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Chaukas")
    app.setOrganizationName("Chaukas")
    for font_file in sorted((ASSETS / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font_file))
    font = QFont(FONT_FAMILY, 10)
    font.setFamilies([FONT_FAMILY, DEVANAGARI_FAMILY])  # Hindi falls back to Noto
    app.setFont(font)
    if not _registered:
        theme = QUrl.fromLocalFile(str(QML_DIR / "Theme.qml"))
        # The stubs declare the names as bytes; PySide6 takes str at runtime.
        qmlRegisterSingletonType(theme, "Chaukas", 1, 0, "Theme")  # type: ignore[call-overload]
        _registered = True
    return app


@dataclass
class LoadedUi:
    engine: QQmlApplicationEngine
    bridge: DashboardBridge
    main_window: QQuickWindow

    def window(self, name: str) -> QQuickWindow:
        found = self.main_window.findChild(QQuickWindow, name)
        if found is None:
            raise ChaukasError(f"no window named {name!r}")
        return found

    def close(self) -> None:
        self.bridge.stop()
        for name in ALERT_WINDOWS:
            self.window(name).close()
        self.main_window.close()
        self.engine.deleteLater()


def load_ui(
    *,
    case: Path | None,
    settings_file: Path | None = None,
    headless: bool = False,
    ablation: str = "E",
    config_paths: Sequence[Path] = (),
    speed: float = 1.0,
    size: tuple[int, int] | None = None,
) -> LoadedUi:
    """Build the whole interface. Call ``create_app`` first."""
    config = config_for(ablation, *config_paths)
    templates = load_templates()
    live = LiveSession(config, Lexicon.load(), templates,
                       case=load_case(case) if case else None)  # fmt: skip
    path = settings_file if settings_file is not None else settings_path()
    bridge = DashboardBridge(live, templates, load_settings(path), path, speed=speed)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("icon", IconProvider(ASSETS / "icons"))
    engine.rootContext().setContextProperty("dashboard", bridge)
    width, height = size or (0, 0)
    engine.setInitialProperties(
        {"headless": headless, "requestedWidth": width, "requestedHeight": height}
    )
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    roots: list[QObject] = engine.rootObjects()
    if not roots or not isinstance(roots[0], QQuickWindow):
        raise ChaukasError("the Chaukas interface failed to load (see the QML errors above)")
    if not headless:
        bridge.start()
    return LoadedUi(engine=engine, bridge=bridge, main_window=roots[0])


def run(
    *,
    case: Path | None,
    ablation: str,
    config_paths: Sequence[Path],
    speed: float,
    screenshot: Path | None,
    at: float,
    page: int,
    size: tuple[int, int],
) -> int:
    """``chaukas ui``: the interactive window, or a headless screenshot."""
    headless = screenshot is not None
    app = create_app(headless=headless)
    ui = load_ui(case=case, headless=headless, ablation=ablation, config_paths=config_paths,
                 speed=speed, size=size if headless else None,
                 settings_file=None)  # fmt: skip
    ui.main_window.setProperty("page", page)
    if screenshot is None:
        return app.exec()

    ui.bridge.jump(at)

    def capture() -> None:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        ui.main_window.grabWindow().save(str(screenshot))
        for name in ALERT_WINDOWS:
            window = ui.window(name)
            if window.isVisible():
                target = screenshot.with_name(f"{screenshot.stem}-{name}{screenshot.suffix}")
                window.grabWindow().save(str(target))
        app.quit()

    QTimer.singleShot(400, capture)
    return app.exec()
