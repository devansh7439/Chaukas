"""The Qt side: icon rendering, the QML bridge, and the real QML loading cleanly.

Runs headless (offscreen platform, software renderer), the same way `chaukas ui
--screenshot` renders. Any QML warning fails the test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSize, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication

from chaukas.ui.app import ASSETS, create_app, load_ui
from chaukas.ui.icons import IconProvider

CASES = Path(__file__).resolve().parents[2] / "eval" / "cases"


@pytest.fixture(scope="module")
def app() -> QGuiApplication:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return create_app(headless=True)


@pytest.fixture
def qt_messages() -> Iterator[list[str]]:
    messages: list[str] = []

    def handler(kind: QtMsgType, context: Any, message: str) -> None:
        if kind != QtMsgType.QtDebugMsg:
            messages.append(message)

    previous = qInstallMessageHandler(handler)
    yield messages
    qInstallMessageHandler(previous)


def pump(app: QGuiApplication, rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


class TestIcons:
    def test_renders_in_the_requested_colour(self, app: QGuiApplication) -> None:
        provider = IconProvider(ASSETS / "icons")
        image = provider.requestImage("square/ff0000", QSize(), QSize(48, 48))
        assert (image.width(), image.height()) == (48, 48)
        colours = {
            image.pixelColor(x, y).name()
            for x in range(48)
            for y in range(48)
            if image.pixelColor(x, y).alpha() > 200
        }
        assert colours == {"#ff0000"}

    def test_unknown_icons_are_blank_not_fatal(self, app: QGuiApplication) -> None:
        image = IconProvider(ASSETS / "icons").requestImage("nope/000000", QSize(), QSize(8, 8))
        assert all(image.pixelColor(x, y).alpha() == 0 for x in range(8) for y in range(8))

    def test_every_icon_the_qml_uses_exists(self) -> None:
        import re

        qml = "\n".join(
            p.read_text(encoding="utf-8") for p in (ASSETS.parent / "qml").glob("*.qml")
        )
        names = set(re.findall(r'(?:icon|name|iconName)\s*:\s*"([a-z0-9-]+)"', qml))
        names |= {"shield-check", "info", "triangle-alert", "octagon-alert"}  # Theme.levelIcon
        missing = sorted(n for n in names if not (ASSETS / "icons" / f"{n}.svg").exists())
        assert missing == []


class TestInterface:
    def test_loads_without_qml_warnings(
        self, app: QGuiApplication, qt_messages: list[str], tmp_path: Path
    ) -> None:
        ui = load_ui(case=CASES / "DA01.yaml", settings_file=tmp_path / "s.json", headless=True)
        pump(app)
        assert qt_messages == []
        assert ui.main_window.isVisible()
        ui.close()

    def test_a_critical_moment_shows_the_pause_card(
        self, app: QGuiApplication, qt_messages: list[str], tmp_path: Path
    ) -> None:
        ui = load_ui(case=CASES / "DA01.yaml", settings_file=tmp_path / "s.json", headless=True)
        ui.bridge.jump(35.0)
        pump(app, 10)
        assert ui.bridge.view["level"] == "critical"
        assert ui.window("criticalWindow").isVisible()
        assert not ui.window("noticeWindow").isVisible()
        ui.bridge.dismiss()
        pump(app, 10)
        assert not ui.window("criticalWindow").isVisible()
        assert qt_messages == []
        ui.close()

    def test_every_page_renders(
        self, app: QGuiApplication, qt_messages: list[str], tmp_path: Path
    ) -> None:
        ui = load_ui(case=CASES / "CT01.yaml", settings_file=tmp_path / "s.json", headless=True)
        ui.bridge.jump(20.0)
        for page in range(4):
            ui.main_window.setProperty("page", page)
            pump(app, 5)
            image = ui.main_window.grabWindow()
            assert not image.isNull()
        ui.bridge.setLanguage("hi")
        pump(app, 5)
        assert qt_messages == []
        ui.close()


class TestBridge:
    def test_typing_a_line_updates_the_view(self, app: QGuiApplication, tmp_path: Path) -> None:
        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True, ablation="E")
        ui.bridge.jump(3.0)
        ui.bridge.say("CBI se bol raha hoon, arrest warrant hai", "caller")
        assert ui.bridge.view["level"] == "notice"
        assert ui.bridge.transcript[-1]["speaker"] == "caller"
        ui.close()

    def test_language_and_contact_are_saved(self, app: QGuiApplication, tmp_path: Path) -> None:
        from chaukas.ui.settings import load_settings

        path = tmp_path / "s.json"
        ui = load_ui(case=None, settings_file=path, headless=True)
        ui.bridge.setLanguage("hi")
        ui.bridge.saveContact("Maa", "+91 98765 43210")
        assert ui.bridge.labels["nav_home"] == "होम"
        saved = load_settings(path)
        assert (saved.language, saved.contact_name) == ("hi", "Maa")
        ui.close()

    def test_end_session_wipes_and_says_so(self, app: QGuiApplication, tmp_path: Path) -> None:
        ui = load_ui(case=CASES / "DA01.yaml", settings_file=tmp_path / "s.json", headless=True)
        ui.bridge.jump(30.0)
        toasts: list[str] = []
        ui.bridge.toast.connect(toasts.append)
        ui.bridge.endSession()
        assert ui.bridge.transcript == []
        assert toasts == ["Temporary conversation data discarded."]
        ui.close()

    def test_pause_toggles(self, app: QGuiApplication, tmp_path: Path) -> None:
        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True)
        ui.bridge.togglePause()
        assert ui.bridge.view["paused"] is True
        ui.bridge.togglePause()
        assert ui.bridge.view["paused"] is False
        ui.close()


class TestClockAndScreenshots:
    def test_ticks_follow_the_clock_at_demo_speed(self, app: QGuiApplication) -> None:
        from chaukas.engine.templates import load_templates
        from chaukas.evaluation.ablation import config_for
        from chaukas.evaluation.cases import load_case
        from chaukas.signals.lexicon import Lexicon
        from chaukas.ui.bridge import DashboardBridge
        from chaukas.ui.live import LiveSession
        from chaukas.ui.settings import UserSettings

        now = [100.0]
        templates = load_templates()
        live = LiveSession(config_for("E"), Lexicon.load(), templates,
                           case=load_case(CASES / "DA01.yaml"))  # fmt: skip
        bridge = DashboardBridge(live, templates, UserSettings(), None, speed=4.0,
                                 clock=lambda: now[0])  # fmt: skip
        bridge.start()
        now[0] += 8.0  # 8 real seconds at 4x = 32 s of call
        bridge.tick()
        bridge.stop()
        assert bridge.view["callTime"] == "00:32"
        assert bridge.view["level"] == "critical"

    def test_screenshot_mode_writes_every_visible_window(
        self, app: QGuiApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from chaukas.ui.app import run

        monkeypatch.setenv("APPDATA", str(tmp_path))  # keep the user's settings untouched
        target = tmp_path / "shots" / "home.png"
        code = run(case=CASES / "DA01.yaml", ablation="E", config_paths=(), speed=1.0,
                   screenshot=target, at=35.0, page=0, size=(1280, 820))  # fmt: skip
        assert code == 0
        assert target.is_file()
        assert (tmp_path / "shots" / "home-criticalWindow.png").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows display affinity")
class TestCaptureExclusion:
    def test_a_real_window_is_excluded_and_restored(self) -> None:
        import ctypes
        from ctypes import wintypes

        from chaukas.ui.capture_exclusion import set_capture_excluded

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = (
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        )  # fmt: skip
        user32.GetWindowDisplayAffinity.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user32.DestroyWindow.argtypes = (wintypes.HWND,)
        hwnd = user32.CreateWindowExW(0, "STATIC", "chaukas-test", 0, 0, 0, 10, 10,
                                      None, None, None, None)  # fmt: skip
        assert hwnd
        try:
            affinity = wintypes.DWORD()
            assert set_capture_excluded(hwnd, True)
            user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
            assert affinity.value == 0x11
            assert set_capture_excluded(hwnd, False)
            user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
            assert affinity.value == 0
        finally:
            user32.DestroyWindow(hwnd)

    def test_no_window_is_a_harmless_no(self) -> None:
        from chaukas.ui.capture_exclusion import set_capture_excluded

        assert set_capture_excluded(0, True) is False

    def test_the_bridge_protects_alert_windows_when_enabled(
        self, app: QGuiApplication, tmp_path: Path
    ) -> None:
        ui = load_ui(case=CASES / "DA01.yaml", settings_file=tmp_path / "s.json", headless=True)
        ui.bridge.setCaptureExclusion(True)
        assert ui.bridge.captureExclusion is True
        ui.bridge.protectWindow(ui.window("criticalWindow"))  # offscreen: no real HWND, no crash
        ui.close()
