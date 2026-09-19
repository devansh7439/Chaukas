from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chaukas.core.errors import ConfigError
from chaukas.core.models import ContextKind, Level, Objective, Stream
from chaukas.evaluation.cases import (
    Category,
    Mark,
    Split,
    case_from_mapping,
    load_case,
    load_cases,
)


def minimal(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "case_id": "X1",
        "category": "benign",
        "scenario": "smoke",
        "split": "dev",
        "author": "me",
        "expected": {"max_level": "quiet", "acceptable_levels": ["quiet"], "objective": "none"},
        "timeline": [{"at": 0.0, "caller": "hello there"}],
    }
    data.update(overrides)
    return data


class TestPackagedCases:
    def test_digital_arrest_case_resolves(self, cases_dir: Path) -> None:
        case = load_case(cases_dir / "DA01.yaml")
        assert case.category is Category.ATTACK
        assert case.split is Split.DEV
        assert case.expectation.max_level is Level.CRITICAL
        assert case.expectation.objective is Objective.MONEY_TRANSFER
        assert case.marks[Mark.HARM] == 42.0
        assert case.marks[Mark.EXPECTED_WARNING] == 19.5
        assert [cue.kind for cue in case.cues] == [
            ContextKind.BANK_PAGE,
            ContextKind.TRANSFER_PAGE,
        ]
        assert [assessment.addressed_to_user for assessment in case.assessments] == [True]
        assert [line.stream for line in case.lines].count(Stream.USER) == 1
        assert case.end_time == 42.0

    def test_line_durations_come_from_word_count(self, cases_dir: Path) -> None:
        case = load_case(cases_dir / "BN07.yaml")
        first = case.lines[0]  # 11 words at 2.5 words/second
        assert first.duration == pytest.approx(4.4)
        assert first.t_end == pytest.approx(4.4)

    def test_load_cases_filters_and_sorts(self, cases_dir: Path) -> None:
        ids = [case.case_id for case in load_cases(cases_dir)]
        assert ids == sorted(ids)
        assert set(ids) == {"BN01", "BN07", "CT01", "DA01"}
        assert load_cases(cases_dir, split=Split.TEST) == ()


class TestTimelineResolution:
    def test_after_chains_from_the_previous_entry(self) -> None:
        case = case_from_mapping(
            minimal(
                timeline=[
                    {"at": 0.0, "caller": "one two three four five", "duration": 2.0},
                    {"after": 1.0, "caller": "next line", "duration": 1.0},
                    {"after": 0.5, "event": "bank_page"},
                ]
            )
        )
        assert [line.t for line in case.lines] == [0.0, 3.0]
        assert case.cues[0].t == 4.5

    def test_absolute_marks_do_not_rewind_the_cursor(self) -> None:
        case = case_from_mapping(
            minimal(
                timeline=[
                    {"at": 10.0, "caller": "hello", "duration": 2.0},
                    {"at": 1.0, "mark": "first_tactic"},
                    {"after": 1.0, "caller": "again", "duration": 1.0},
                ]
            )
        )
        assert case.marks[Mark.FIRST_TACTIC] == 1.0
        assert case.lines[1].t == 13.0


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (minimal(timeline=[{"at": 0.0, "caller": "a", "user": "b"}]), "exactly one"),
        (minimal(timeline=[{"at": 1.0, "after": 1.0, "caller": "a"}]), "either 'at' or 'after'"),
        (minimal(timeline=[{"at": 0.0, "event": "bank_page", "duration": 2.0}]), "duration"),
        (minimal(timeline=[]), "timeline"),
        (minimal(timeline=[{"at": 0.0, "event": "screensaver"}]), "event"),
        (
            minimal(
                expected={
                    "max_level": "critical",
                    "acceptable_levels": ["quiet"],
                    "objective": "none",
                }
            ),
            "max_level must be one of",
        ),
        (
            minimal(
                expected={"max_level": "panic", "acceptable_levels": ["quiet"], "objective": "none"}
            ),
            "unknown level",
        ),
        (minimal(category="attack"), "need a 'harm' mark"),
        (
            minimal(
                timeline=[{"at": 0.0, "mark": "harm"}, {"at": 1.0, "mark": "harm"}],
                category="attack",
            ),
            "appears twice",
        ),
    ],
)
def test_invalid_cases(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        case_from_mapping(data)


def test_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_cases(tmp_path / "nope")


def test_duplicate_case_ids(tmp_path: Path) -> None:
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(
            "case_id: SAME\ncategory: benign\nscenario: s\nsplit: dev\nauthor: me\n"
            "expected: {max_level: quiet, acceptable_levels: [quiet], objective: none}\n"
            "timeline: [{at: 0.0, caller: hello}]\n",
            encoding="utf-8",
        )
    with pytest.raises(ConfigError, match="duplicate case_id"):
        load_cases(tmp_path)
