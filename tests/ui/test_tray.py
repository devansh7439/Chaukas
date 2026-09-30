"""The notification-area icon while live protection runs: the level at a glance, and Open,
Pause / Resume and Quit."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from chaukas.ui.tray import Tray, tray_icon, tray_tooltip

CASES = Path(__file__).resolve().parents[2] / "eval" / "cases"


class TestText:
    def test_tooltip_names_the_level(self) -> None:
        assert tray_tooltip({"levelTitle": "Critical", "paused": False}) == "Chaukas: Critical"

    def test_tooltip_says_when_paused(self) -> None:
        view = {"levelTitle": "Protected", "paused": True}
        assert tray_tooltip(view) == "Chaukas: Protected (paused: not listening)"

    @pytest.mark.parametrize(
        ("level", "icon"),
        [("quiet", "shield-check"), ("notice", "shield-alert"), ("critical", "shield-alert")],
    )
    def test_icon_by_level(self, level: str, icon: str) -> None:
        assert tray_icon({"level": level})[0] == icon


class TestQt:
    @pytest.fixture
    def ui(self):  # type: ignore[no-untyped-def]
        from chaukas.ui.app import create_app, load_ui

        app = create_app(headless=True)
        loaded = load_ui(case=CASES / "DA01.yaml", headless=True, ablation="E",
                         config_paths=(), speed=1.0, size=(1200, 800),
                         settings_file=None)  # fmt: skip
        yield app, loaded
        loaded.close()

    def test_follows_the_level_and_pauses(self, ui) -> None:  # type: ignore[no-untyped-def]
        app, loaded = ui
        tray = Tray(loaded.bridge, loaded.main_window, app)
        assert tray.tooltip() == "Chaukas: " + loaded.bridge.view["levelTitle"]
        loaded.bridge.jump(40.0)  # the scripted call has reached its critical moment
        assert loaded.bridge.view["level"] in ("critical", "critical_recovery")
        assert tray.tooltip().startswith("Chaukas: ")
        assert tray.tooltip() != "Chaukas: " + "Protected"
        assert not tray.icon().isNull()
        tray.toggle_pause()
        assert loaded.bridge.view["paused"] is True
        assert tray.pause_label() == "Resume listening"
        tray.toggle_pause()
        assert tray.pause_label() == "Pause listening"
        tray.hide()
