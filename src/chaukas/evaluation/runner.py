"""Replay a case script through the session pipeline.

One discrete-event loop merges speech lines, context cues, evaluation ticks and, when a
real model is attached, LLM answers. An LLM call starts whenever the trigger policy says
so and its answer is scheduled at ``request time + measured latency``, so the engine sees
it exactly when a live session would have. With a real model, scripted verdicts in the
case file are ignored.
"""

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
from chaukas.llm.reasoner import LLMOutcome, Reasoner
from chaukas.signals.extractor import SignalExtractor
from chaukas.signals.lexicon import Lexicon

SETTLE_S: Final = 60.0  # keep ticking after the last event so de-escalation is visible


class _Tick:
    __slots__ = ()


_TICK: Final = _Tick()

_Item = SpeechLine | ContextCue | AssessmentCue | LLMOutcome | _Tick


@dataclass(frozen=True, slots=True)
class CaseRun:
    """Every evaluation produced while replaying one case."""

    case: Case
    snapshots: tuple[Snapshot, ...]
    llm_outcomes: tuple[LLMOutcome, ...] = ()

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
    reasoner: Reasoner | None = None,
) -> CaseRun:
    """Replay ``case`` as transcript text and collect every evaluation.

    Without a ``reasoner`` (or in a configuration that doesn't use the LLM), the only LLM
    verdicts are the ones the case scripts.
    """
    session = Session(
        SignalExtractor(lexicon, config.signals),
        RiskEngine.from_config(config, templates),
        tick_s=tick_s,
        session_id=case.case_id,
    )
    model = reasoner if reasoner is not None and config.ablation.use_llm else None
    if model is not None:
        model.reset()

    end = case.end_time + settle_s
    timeline: Timeline[_Item] = Timeline()
    for line in case.lines:
        timeline.push(line.t_end, line)  # a line exists once speech recognition closes it
    for cue in case.cues:
        timeline.push(cue.t, cue)
    if model is None:
        for verdict in case.assessments:
            timeline.push(verdict.t, verdict)
    for step in range(1, int(end / tick_s) + 1):
        timeline.push(step * tick_s, _TICK)

    snapshots: list[Snapshot] = []
    outcomes: list[LLMOutcome] = []
    while timeline:
        t, item = timeline.pop()
        if isinstance(item, _Tick):
            snapshots.extend(session.advance_to(t))
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
            if model is not None:
                model.observe_segment(segment, session.last_signals)
        elif isinstance(item, ContextCue):
            event = ContextEvent(t=item.t, kind=item.kind, detail=item.detail)
            snapshots.extend(session.feed_context(event))
            if model is not None:
                model.observe_context(event, session.state.level)
        elif isinstance(item, AssessmentCue):
            snapshots.extend(
                session.feed_assessment(
                    LLMAssessment(
                        t=item.t,
                        addressed_to_user=item.addressed_to_user,
                        suspected_objective=item.objective,
                    )
                )
            )
        else:
            assert model is not None
            model.finish(item)
            outcomes.append(item)
            snapshots.extend(session.feed_llm(item.t_available, item.signals, item.assessment))

        if model is not None and model.due(session.now):
            outcome = model.execute(model.request(session.now, session.state))
            timeline.push(outcome.t_available, outcome)

    snapshots.extend(session.advance_to(end))
    return CaseRun(case=case, snapshots=tuple(snapshots), llm_outcomes=tuple(outcomes))
