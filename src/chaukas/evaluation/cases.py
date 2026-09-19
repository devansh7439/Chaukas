"""Evaluation case scripts.

A case is a YAML file: metadata, the expected outcome, and a timeline of caller/user lines,
context cues and annotation marks. One script serves three purposes:

* transcript replay through signals and the engine, which works from day one;
* audio assembly later (each line recorded separately, then placed at its time);
* labels: ``first_tactic``, ``expected_warning`` and ``harm`` are written by whoever wrote
  the case, never derived from Chaukas's own detectors.

Times are seconds from the start of the call. An entry uses ``at`` for an absolute time or
``after`` for a gap after the previous entry; speech without an explicit ``duration`` is
estimated from its word count.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Final, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

from chaukas.core.errors import ConfigError
from chaukas.core.models import ContextKind, Level, Objective, Stream
from chaukas.core.yamlio import read_file_mapping

WORDS_PER_SECOND: Final = 2.5  # rough speaking rate when a line has no explicit duration
MIN_LINE_DURATION: Final = 0.6


class Category(StrEnum):
    ATTACK = "attack"
    BENIGN = "benign"


class Split(StrEnum):
    DEV = "dev"
    TEST = "test"


class Mark(StrEnum):
    """Hand-written annotations used as labels."""

    FIRST_TACTIC = "first_tactic"
    EXPECTED_WARNING = "expected_warning"
    HARM = "harm"


def _as_level(value: Any) -> Any:
    return Level.parse(value) if isinstance(value, str) else value


LevelName = Annotated[Level, BeforeValidator(_as_level)]


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _LLMSpec(_Strict):
    """A scripted LLM verdict. Dev cases only: never script the LLM in the real dataset."""

    addressed_to_user: bool
    objective: Objective = Objective.NONE


class _EntrySpec(_Strict):
    at: float | None = Field(default=None, ge=0.0)
    after: float | None = Field(default=None, ge=0.0)
    duration: float | None = Field(default=None, gt=0.0)
    caller: str | None = None
    user: str | None = None
    event: ContextKind | None = None
    detail: str = ""
    mark: Mark | None = None
    llm: _LLMSpec | None = None

    @model_validator(mode="after")
    def _exactly_one_payload(self) -> Self:
        payloads = [
            name
            for name in ("caller", "user", "event", "mark", "llm")
            if getattr(self, name) is not None
        ]
        if len(payloads) != 1:
            raise ValueError(
                f"each entry needs exactly one of caller/user/event/mark/llm, got {payloads}"
            )
        if self.at is not None and self.after is not None:
            raise ValueError("an entry sets either 'at' or 'after', not both")
        if self.duration is not None and self.caller is None and self.user is None:
            raise ValueError("only speech entries can have a duration")
        return self


class _ExpectedSpec(_Strict):
    max_level: LevelName
    acceptable_levels: list[LevelName] = Field(min_length=1)
    objective: Objective


class _CaseSpec(_Strict):
    case_id: str = Field(min_length=1)
    category: Category
    scenario: str = Field(min_length=1)
    split: Split
    author: str = Field(min_length=1)
    language: str = "en"
    notes: str = ""
    expected: _ExpectedSpec
    timeline: list[_EntrySpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_expectations(self) -> Self:
        if self.expected.max_level not in self.expected.acceptable_levels:
            raise ValueError("max_level must be one of acceptable_levels")
        return self


@dataclass(frozen=True, slots=True)
class SpeechLine:
    t: float
    duration: float
    stream: Stream
    text: str

    @property
    def t_end(self) -> float:
        return self.t + self.duration


@dataclass(frozen=True, slots=True)
class ContextCue:
    t: float
    kind: ContextKind
    detail: str


@dataclass(frozen=True, slots=True)
class AssessmentCue:
    """A scripted LLM verdict (dev cases only)."""

    t: float
    addressed_to_user: bool
    objective: Objective


@dataclass(frozen=True, slots=True)
class Expectation:
    max_level: Level
    acceptable_levels: frozenset[Level]
    objective: Objective


@dataclass(frozen=True, slots=True)
class Case:
    """A resolved case: absolute times, ready to replay or score."""

    case_id: str
    category: Category
    scenario: str
    split: Split
    author: str
    language: str
    notes: str
    expectation: Expectation
    lines: tuple[SpeechLine, ...]
    cues: tuple[ContextCue, ...]
    assessments: tuple[AssessmentCue, ...]
    marks: Mapping[Mark, float]

    @property
    def end_time(self) -> float:
        times = [line.t_end for line in self.lines]
        times.extend(cue.t for cue in self.cues)
        times.extend(cue.t for cue in self.assessments)
        times.extend(self.marks.values())
        return max(times, default=0.0)

    @property
    def harm_t(self) -> float | None:
        return self.marks.get(Mark.HARM)

    @property
    def first_tactic_t(self) -> float | None:
        return self.marks.get(Mark.FIRST_TACTIC)

    @property
    def expected_warning_t(self) -> float | None:
        return self.marks.get(Mark.EXPECTED_WARNING)


def case_from_mapping(data: Mapping[str, Any], origin: str = "case") -> Case:
    """Validate a case mapping and resolve its timeline to absolute times."""
    try:
        spec = _CaseSpec.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid case {origin}:\n{exc}") from exc

    lines: list[SpeechLine] = []
    cues: list[ContextCue] = []
    assessments: list[AssessmentCue] = []
    marks: dict[Mark, float] = {}
    cursor = 0.0
    for entry in spec.timeline:
        t = entry.at if entry.at is not None else cursor + (entry.after or 0.0)
        if entry.caller is not None or entry.user is not None:
            stream = Stream.CALLER if entry.caller is not None else Stream.USER
            text = entry.caller if entry.caller is not None else entry.user
            assert text is not None
            duration = entry.duration or _estimate_duration(text)
            lines.append(SpeechLine(t=t, duration=duration, stream=stream, text=text))
            cursor = max(cursor, t + duration)
        elif entry.event is not None:
            cues.append(ContextCue(t=t, kind=entry.event, detail=entry.detail))
            cursor = max(cursor, t)
        elif entry.llm is not None:
            assessments.append(
                AssessmentCue(
                    t=t,
                    addressed_to_user=entry.llm.addressed_to_user,
                    objective=entry.llm.objective,
                )
            )
            cursor = max(cursor, t)
        else:
            assert entry.mark is not None
            if entry.mark in marks:
                raise ConfigError(f"invalid case {origin}: mark {entry.mark.value!r} appears twice")
            marks[entry.mark] = t
            cursor = max(cursor, t)

    if spec.category is Category.ATTACK and Mark.HARM not in marks:
        raise ConfigError(f"invalid case {origin}: attack cases need a 'harm' mark")

    return Case(
        case_id=spec.case_id,
        category=spec.category,
        scenario=spec.scenario,
        split=spec.split,
        author=spec.author,
        language=spec.language,
        notes=spec.notes,
        expectation=Expectation(
            max_level=spec.expected.max_level,
            acceptable_levels=frozenset(spec.expected.acceptable_levels),
            objective=spec.expected.objective,
        ),
        lines=tuple(lines),
        cues=tuple(cues),
        assessments=tuple(assessments),
        marks=MappingProxyType(marks),
    )


def load_case(path: Path) -> Case:
    """Load one case script."""
    return case_from_mapping(read_file_mapping(path, "case"), origin=str(path))


def load_cases(directory: Path, *, split: Split | None = None) -> tuple[Case, ...]:
    """Load every ``*.yaml`` case in ``directory``, optionally filtered by split."""
    if not directory.is_dir():
        raise ConfigError(f"case directory {directory} does not exist")
    cases = [load_case(path) for path in sorted(directory.glob("*.yaml"))]
    chosen = [case for case in cases if split is None or case.split is split]
    _check_unique_ids(chosen)
    return tuple(sorted(chosen, key=lambda case: case.case_id))


def _check_unique_ids(cases: Iterable[Case]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise ConfigError(f"duplicate case_id {case.case_id!r}")
        seen.add(case.case_id)


def _estimate_duration(text: str) -> float:
    words = max(1, len(text.split()))
    return max(MIN_LINE_DURATION, words / WORDS_PER_SECOND)
