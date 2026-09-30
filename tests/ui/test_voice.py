"""Spoken alerts: when the level rises to a warning or higher, Chaukas says why out loud.
It never reacts to its own voice: every sentence it speaks is suppressed as evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaukas.core.config import load_config
from chaukas.core.models import Level, Segment, Stream
from chaukas.signals.extractor import SignalExtractor
from chaukas.signals.lexicon import Lexicon
from chaukas.ui.strings import ALERTS
from chaukas.ui.voice import spoken_alert

L = Level
CASES = Path(__file__).resolve().parents[2] / "eval" / "cases"


class TestWhatIsSaid:
    def test_a_notice_is_not_spoken(self) -> None:
        assert spoken_alert(L.QUIET, L.NOTICE, "unclear", "en") is None

    def test_a_warning_says_someone_may_be_pressuring_you(self) -> None:
        assert spoken_alert(L.NOTICE, L.WARNING, "unclear", "en") == ALERTS["pressure"].en

    @pytest.mark.parametrize(
        ("objective", "key"),
        [("money_transfer", "authority_fact"), ("credential_disclosure", "otp_pre"),
         ("remote_control", "remote")],
    )  # fmt: skip
    def test_critical_says_pause_and_the_matching_fact(self, objective: str, key: str) -> None:
        said = spoken_alert(L.WARNING, L.CRITICAL, objective, "en")
        assert said == f"{ALERTS['pause'].en} {ALERTS[key].en}"

    def test_after_a_code_is_read_out_it_says_what_to_do(self) -> None:
        said = spoken_alert(L.CRITICAL, L.CRITICAL_RECOVERY, "credential_disclosure", "en")
        assert said == ALERTS["otp_recovery"].en

    @pytest.mark.parametrize(
        ("before", "after"),
        [(L.CRITICAL, L.CRITICAL), (L.CRITICAL, L.WARNING), (L.WARNING, L.NOTICE)],
    )
    def test_nothing_is_repeated_and_nothing_is_said_on_the_way_down(
        self, before: Level, after: Level
    ) -> None:
        assert spoken_alert(before, after, "money_transfer", "en") is None

    def test_hindi(self) -> None:
        assert spoken_alert(L.NOTICE, L.WARNING, "unclear", "hi") == ALERTS["pressure"].hi


class TestNeverHearsItself:
    @pytest.mark.parametrize("language", ["en", "hi"])
    @pytest.mark.parametrize(
        ("before", "after", "objective"),
        [(L.NOTICE, L.WARNING, "unclear"), (L.WARNING, L.CRITICAL, "money_transfer"),
         (L.WARNING, L.CRITICAL, "credential_disclosure"),
         (L.WARNING, L.CRITICAL, "remote_control"),
         (L.CRITICAL, L.CRITICAL_RECOVERY, "credential_disclosure")],
    )  # fmt: skip
    def test_every_spoken_alert_is_no_evidence_when_heard_back(
        self, language: str, before: Level, after: Level, objective: str
    ) -> None:
        said = spoken_alert(before, after, objective, language)  # type: ignore[arg-type]
        assert said is not None
        extractor = SignalExtractor(Lexicon.load(), load_config().signals)
        heard = Segment(session_id="s", seg_id=1, stream=Stream.CALLER, t_start=0.0,
                        t_end=5.0, text=said)  # fmt: skip
        assert extractor.extract(heard) == []


class TestFollowsTheDashboard:
    def test_speaks_once_per_rise_during_the_demo_call(self) -> None:
        pytest.importorskip("PySide6.QtWidgets")
        from chaukas.ui.app import create_app, load_ui
        from chaukas.ui.voice import AlertVoice

        create_app(headless=True)
        ui = load_ui(case=CASES / "DA01.yaml", headless=True, ablation="E", config_paths=(),
                     speed=1.0, size=(1200, 800), settings_file=None)  # fmt: skip
        said: list[str] = []
        AlertVoice(ui.bridge, said.append)
        for t in (5.0, 10.0, 21.0, 30.0, 35.0):  # notice, warning, critical, still critical
            ui.bridge.jump(t)
        ui.close()
        assert said == [ALERTS["pressure"].en,
                        f"{ALERTS['pause'].en} {ALERTS['authority_fact'].en}"]  # fmt: skip


def test_the_windows_speaker_finds_a_voice_without_speaking() -> None:
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows speech")
    pytest.importorskip("PySide6.QtTextToSpeech")
    from chaukas.ui.app import create_app
    from chaukas.ui.voice import QtSpeaker

    create_app(headless=True)
    speaker = QtSpeaker()
    assert "en" in speaker.languages
    assert speaker.voice_name()  # an installed voice (Indian English preferred)
