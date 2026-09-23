"""The session pipeline: segments and context in, risk snapshots out.

A session owns the signal extractor and the risk engine and decides *when* to evaluate:
after every input, and on a fixed tick so that hysteresis and evidence decay keep moving
while nothing happens. Replay, evaluation and (later) the live app all drive this same
object; only the source of segments differs. Time is supplied by the caller, so a replay
can run a two-hour call in milliseconds while the live app passes its monotonic clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from chaukas.core.models import ContextEvent, Level, LLMAssessment, RiskState, Segment, Signal
from chaukas.engine.risk import RiskEngine
from chaukas.signals.extractor import SignalExtractor


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One evaluation, with whether it changed the displayed level."""

    state: RiskState
    changed: bool

    @property
    def t(self) -> float:
        return self.state.t

    @property
    def level(self) -> Level:
        return self.state.level


class Session:
    """One call. Not thread-safe: the live app drives it from the engine thread."""

    __slots__ = (
        "_engine",
        "_extractor",
        "_last_level",
        "_now",
        "_seg_id",
        "_session_id",
        "_tick_s",
    )

    def __init__(
        self,
        extractor: SignalExtractor,
        engine: RiskEngine,
        *,
        tick_s: float = 1.0,
        session_id: str = "session",
    ) -> None:
        if tick_s <= 0.0:
            raise ValueError(f"tick_s must be positive, got {tick_s}")
        self._extractor = extractor
        self._engine = engine
        self._tick_s = tick_s
        self._session_id = session_id
        self._now = 0.0
        self._seg_id = 0
        self._last_level = Level.QUIET

    @property
    def now(self) -> float:
        return self._now

    @property
    def session_id(self) -> str:
        return self._session_id

    def next_segment_id(self) -> int:
        """Segment ids are handed out in order, so LLM replies can cite them."""
        seg_id = self._seg_id
        self._seg_id += 1
        return seg_id

    def feed_segment(self, segment: Segment) -> list[Snapshot]:
        """Extract signals from a transcript segment and evaluate."""
        snapshots = self.advance_to(segment.t_start)
        self._engine.on_segment(segment)
        for signal in self._extractor.extract(segment):
            self._engine.on_signal(signal)
        snapshots.append(self._evaluate(max(segment.t_end, self._now)))
        return snapshots

    def feed_context(self, event: ContextEvent) -> list[Snapshot]:
        snapshots = self.advance_to(event.t)
        self._engine.on_context(event)
        snapshots.append(self._evaluate(max(event.t, self._now)))
        return snapshots

    def feed_signal(self, signal: Signal) -> list[Snapshot]:
        """A signal from outside the extractor (the LLM layer), evaluated at the current time."""
        self._extractor.observe(signal)
        self._engine.on_signal(signal)
        return [self._evaluate(self._now)]

    def feed_assessment(self, assessment: LLMAssessment) -> list[Snapshot]:
        snapshots = self.advance_to(assessment.t)
        self._engine.on_assessment(assessment)
        snapshots.append(self._evaluate(max(assessment.t, self._now)))
        return snapshots

    def dismiss(self) -> list[Snapshot]:
        """The user acknowledged the current alert."""
        self._engine.dismiss(self._now)
        return [self._evaluate(self._now)]

    def advance_to(self, t: float) -> list[Snapshot]:
        """Evaluate on each tick up to ``t``. Going backwards is a no-op."""
        snapshots: list[Snapshot] = []
        while self._now + self._tick_s <= t:
            snapshots.append(self._evaluate(self._now + self._tick_s))
        return snapshots

    def reset(self) -> None:
        """Session end: wipe the engine and extractor state, keep the clock."""
        self._engine.reset()
        self._extractor.reset()
        self._last_level = Level.QUIET

    def _evaluate(self, t: float) -> Snapshot:
        self._now = max(self._now, t)
        state = self._engine.evaluate(self._now)
        changed = state.level is not self._last_level
        self._last_level = state.level
        return Snapshot(state=state, changed=changed)
