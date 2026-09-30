"""First run: a welcome sheet says what Chaukas listens to, what stays private, and that
the person always decides. Shown once, in live mode only (demos and screenshots never)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaukas.ui.copy import labels
from chaukas.ui.settings import UserSettings, load_settings, save_settings

pytest.importorskip("PySide6.QtWidgets")

WELCOME_KEYS = ("welcome_title", "welcome_listen", "welcome_private", "welcome_decide",
                "welcome_start")  # fmt: skip


class TestSettings:
    def test_not_welcomed_by_default_and_remembered(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        assert load_settings(path).welcomed is False
        save_settings(UserSettings(welcomed=True), path)
        assert load_settings(path).welcomed is True

    def test_a_wrong_type_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"welcomed": "yes"}), encoding="utf-8")
        assert load_settings(path).welcomed is False


@pytest.mark.parametrize("language", ["en", "hi"])
def test_the_welcome_is_written_in_both_languages(language: str) -> None:
    text = labels(language)  # type: ignore[arg-type]
    for key in WELCOME_KEYS:
        assert text[key].strip(), key


class TestSheet:
    @staticmethod
    def load(tmp_path: Path, *, welcome: bool):  # type: ignore[no-untyped-def]
        from chaukas.ui.app import create_app, load_ui

        create_app(headless=True)
        return load_ui(case=None, headless=True, ablation="E", config_paths=(), speed=1.0,
                       size=(1200, 800), settings_file=tmp_path / "settings.json",
                       welcome=welcome)  # fmt: skip

    @staticmethod
    def sheet_kind(ui) -> str:  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QObject

        sheet = ui.main_window.findChild(QObject, "sheet")
        return str(sheet.property("kind"))

    def test_first_live_run_shows_it_and_start_remembers(self, tmp_path: Path) -> None:
        ui = self.load(tmp_path, welcome=True)
        assert ui.bridge.property("firstRun") is True
        assert self.sheet_kind(ui) == "welcome"
        ui.bridge.finishWelcome()
        assert ui.bridge.property("firstRun") is False
        assert load_settings(tmp_path / "settings.json").welcomed is True
        ui.close()

    def test_demos_never_show_it(self, tmp_path: Path) -> None:
        ui = self.load(tmp_path, welcome=False)
        assert ui.bridge.property("firstRun") is False
        assert self.sheet_kind(ui) == ""
        ui.close()

    def test_not_shown_again_once_welcomed(self, tmp_path: Path) -> None:
        save_settings(UserSettings(welcomed=True), tmp_path / "settings.json")
        ui = self.load(tmp_path, welcome=True)
        assert self.sheet_kind(ui) == ""
        ui.close()
