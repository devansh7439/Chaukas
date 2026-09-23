"""The live session behind the dashboard, and the user's saved settings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaukas.core.models import Level, Stream
from chaukas.engine.templates import load_templates
from chaukas.evaluation.ablation import config_for
from chaukas.evaluation.cases import load_case
from chaukas.signals.lexicon import Lexicon
from chaukas.ui.live import LiveSession
from chaukas.ui.presenter import transcript_view
from chaukas.ui.settings import UserSettings, load_settings, save_settings

CASES = Path(__file__).resolve().parents[2] / "eval" / "cases"


@pytest.fixture(scope="module")
def lexicon() -> Lexicon:
    return Lexicon.load()


def live(lexicon: Lexicon, case: str | None = None, ablation: str = "D") -> LiveSession:
    return LiveSession(
        config_for(ablation),
        lexicon,
        load_templates(),
        case=load_case(CASES / f"{case}.yaml") if case else None,
    )


class TestReplay:
    def test_a_case_plays_out_in_time(self, lexicon: Lexicon) -> None:
        session = live(lexicon, "DA01")
        session.advance(3.0)
        assert session.transcript == ()  # the first line ends at 4.0 s
        session.advance(30.0)
        assert session.state.level is Level.CRITICAL
        speakers = [entry.speaker for entry in session.transcript]
        assert speakers[:3] == ["caller", "caller", "user"]
        assert "system" in speakers  # the bank page appears in the call log

    def test_history_records_every_evaluation(self, lexicon: Lexicon) -> None:
        session = live(lexicon, "DA01")
        session.advance(10.0)
        times = [t for t, _ in session.history]
        assert times == sorted(times)
        assert times[-1] == pytest.approx(10.0)

    def test_time_never_moves_backwards(self, lexicon: Lexicon) -> None:
        session = live(lexicon, "DA01")
        session.advance(10.0)
        session.advance(5.0)
        assert session.now == 10.0


class TestTypedLines:
    def test_a_typed_caller_line_is_evidence(self, lexicon: Lexicon) -> None:
        session = live(lexicon, ablation="E")
        session.advance(5.0)
        assert session.say("Main CBI se bol raha hoon, arrest warrant hai", Stream.CALLER)
        assert session.state.level is Level.NOTICE
        (entry,) = session.transcript
        assert entry.speaker == "caller"
        assert set(entry.kinds) == {"authority", "threat"}

    def test_blank_lines_are_ignored(self, lexicon: Lexicon) -> None:
        session = live(lexicon)
        assert not session.say("   ", Stream.CALLER)
        assert session.transcript == ()

    def test_digits_after_an_otp_request(self, lexicon: Lexicon) -> None:
        session = live(lexicon, ablation="E")
        session.advance(1.0)
        session.say("SBI bank se bol raha hoon, OTP batao", Stream.CALLER)
        session.advance(3.0)
        session.say("4 5 6 7", Stream.USER)
        assert session.state.level is Level.CRITICAL_RECOVERY


class TestControls:
    def test_pause_drops_what_it_would_have_heard(self, lexicon: Lexicon) -> None:
        session = live(lexicon, "DA01")
        session.set_paused(True)
        session.advance(30.0)
        assert not session.say("arrest warrant", Stream.CALLER)
        assert session.transcript == ()
        assert session.state.level is Level.QUIET
        session.set_paused(False)
        assert not session.paused

    def test_end_session_wipes_everything(self, lexicon: Lexicon) -> None:
        session = live(lexicon, "DA01")
        session.advance(30.0)
        session.end_session()
        assert session.transcript == ()
        assert session.history == []
        session.advance(90.0)  # the rest of the script is gone too
        assert session.transcript == ()
        assert session.state.level is Level.QUIET
        assert session.state.reasons == ()

    def test_dismiss_marks_the_state(self, lexicon: Lexicon) -> None:
        session = live(lexicon, "DA01")
        session.advance(30.0)
        session.dismiss()
        assert session.state.dismissed


def test_transcript_view_translates_system_lines(lexicon: Lexicon) -> None:
    session = live(lexicon, "DA01")
    session.advance(30.0)
    views = transcript_view(session.transcript, "en")
    system = next(view for view in views if view["speaker"] == "system")
    assert system["text"] == "A banking page is open"
    caller = views[0]
    assert caller["time"] == "00:00"
    assert "Authority" in caller["tags"]


class TestSettings:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        settings = UserSettings(language="hi", contact_name="Maa", contact_number="+91 98765 43210")
        save_settings(settings, path)
        assert load_settings(path) == settings

    def test_missing_or_corrupt_files_give_defaults(self, tmp_path: Path) -> None:
        assert load_settings(tmp_path / "missing.json") == UserSettings()
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{not json", encoding="utf-8")
        assert load_settings(corrupt) == UserSettings()

    def test_unknown_or_bad_fields_are_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"language": "fr", "contact_name": "Papa", "x": 1}),
                        encoding="utf-8")  # fmt: skip
        assert load_settings(path) == UserSettings(contact_name="Papa")

    @pytest.mark.parametrize(
        ("number", "clean"),
        [("+91 98765-43210", "+91 98765-43210"), ("98765 abc 43210", "98765  43210"), ("", "")],
    )
    def test_numbers_keep_only_dialable_characters(self, number: str, clean: str) -> None:
        assert UserSettings(contact_number=number).contact_number == clean
