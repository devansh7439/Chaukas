"""Replay a case script through the session pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from chaukas.core.config import ChaukasConfig
from chaukas.core.models import ContextEvent, Level, LLMAssessment, Objective, RiskState, Segment
from chaukas.core.timeline import Timeline
from chaukas.engine.risk import RiskEngine
from chaukas.engine.templates import ChainTemplate
from chaukas.evaluation.cases import AssessmentCue, Case, ContextCue, SpeechLine
from chaukas.evaluation.session import Session, Snapshot
from chaukas.signals.extractor import SignalExtractor
from chaukas.signals.lexicon import Lexicon

SETTLE_S: Final = 60.0  # keep ticking after the last event so de-escalation is visible


@dataclass(frozen=True, slots=True)
class CaseRun:
    """Every evaluation produced while replaying one case."""

    case: Case
    snapshots: tuple[Snapshot, ...]

    @property
    def final_state(self) -> RiskState | None:
        return self.snapshots[-1].state if self.snapshots else None

    @property
    def max_level(self) -> Level:
        return max((snapshot.level for snapshot in self.snapshots), default=Level.QUIET)

    @property
    def transitions(self) -> tuple[Snapshot, ...]:
        return tuple(snapshot for snapshot in self.snapshots if snapshot.changed)

    def first_time_at_least(self, level: Level) -> float | None:
        """When the displayed level first reached ``level``."""
        for snapshot in self.snapshots:
            if snapshot.level >= level:
                return snapshot.t
        return None

    def objective_when(self, level: Level) -> Objective | None:
        """The suspected objective at the moment ``level`` was first reached."""
        for snapshot in self.snapshots:
            if snapshot.level >= level:
                return snapshot.state.objective
        return None


def run_case(
    case: Case,
    *,
    config: ChaukasConfig,
    lexicon: Lexicon,
    templates: Sequence[ChainTemplate] | None = None,
    tick_s: float = 1.0,
    settle_s: float = SETTLE_S,
) -> CaseRun:
    """Replay ``case`` as transcript text (no audio, no LLM) and collect every evaluation."""
    session = Session(
        SignalExtractor(lexicon, config.signals),
        RiskEngine.from_config(config, templates),
        tick_s=tick_s,
        session_id=case.case_id,
    )
    timeline: Timeline[SpeechLine | ContextCue | AssessmentCue] = Timeline()
    for line in case.lines:
        timeline.push(line.t, line)
    for cue in case.cues:
        timeline.push(cue.t, cue)
    for verdict in case.assessments:
        timeline.push(verdict.t, verdict)

    snapshots: list[Snapshot] = []
    while timeline:
        _, item = timeline.pop()
        if isinstance(item, AssessmentCue):
            snapshots.extend(
                session.feed_assessment(
                    LLMAssessment(
                        t=item.t,
                        addressed_to_user=item.addressed_to_user,
                        suspected_objective=item.objective,
                    )
                )
            )
        elif isinstance(item, SpeechLine):
            segment = Segment(
                session_id=case.case_id,
                seg_id=session.next_segment_id(),
                stream=item.stream,
                t_start=item.t,
                t_end=item.t_end,
                text=item.text,
            )
            snapshots.extend(session.feed_segment(segment))
        else:
            snapshots.extend(
                session.feed_context(ContextEvent(t=item.t, kind=item.kind, detail=item.detail))
            )
    snapshots.extend(session.advance_to(case.end_time + settle_s))
    return CaseRun(case=case, snapshots=tuple(snapshots))
