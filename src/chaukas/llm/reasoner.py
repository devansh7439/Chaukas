"""The reasoner: trigger policy, transcript window, prompt, client and evidence guard.

Split into three steps so the slow part can run on its own thread:

* ``request(now, state)`` runs on the engine thread: it snapshots the prompt window and
  marks the call in flight;
* ``execute(request)`` does the network call and the guard; it touches no reasoner state,
  so a worker thread can run it;
* ``finish(outcome)`` runs back on the engine thread and frees the trigger.

Replay and evaluation call all three in a row and schedule the outcome at
``t_request + latency`` on the virtual clock.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from chaukas.core.config import ChaukasConfig
from chaukas.core.models import ContextEvent, Level, LLMAssessment, RiskState, Segment, Signal
from chaukas.core.window import TimeWindow
from chaukas.llm.client import Chat, LLMCall, assess
from chaukas.llm.evidence import GuardResult, apply_guard
from chaukas.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from chaukas.llm.trigger import TriggerPolicy


@dataclass(frozen=True, slots=True)
class LLMRequest:
    t: float
    lines: Mapping[int, Segment]  # every line shown to the model, by seg_id
    prompt: str


@dataclass(frozen=True, slots=True)
class LLMOutcome:
    t_request: float
    call: LLMCall
    guard: GuardResult | None

    @property
    def t_available(self) -> float:
        """When the answer exists: request time plus measured latency."""
        return self.t_request + self.call.latency_s

    @property
    def signals(self) -> tuple[Signal, ...]:
        return self.guard.signals if self.guard is not None else ()

    @property
    def assessment(self) -> LLMAssessment | None:
        return self.guard.assessment if self.guard is not None else None


class Reasoner:
    __slots__ = ("_chat", "_config", "_context", "_transcript", "_trigger")

    def __init__(self, chat: Chat, config: ChaukasConfig) -> None:
        self._chat = chat
        self._config = config
        self._trigger = TriggerPolicy(config.llm)
        self._transcript: TimeWindow[Segment] = TimeWindow(config.llm.window_s)
        self._context: TimeWindow[ContextEvent] = TimeWindow(config.llm.context_lookback_s)

    def observe_segment(self, segment: Segment, signals: Sequence[Signal]) -> None:
        self._transcript.add(segment.t_start, segment)
        self._trigger.on_segment(segment)
        for signal in signals:
            self._trigger.on_signal(signal)

    def observe_context(self, event: ContextEvent, level: Level) -> None:
        if event.objective is None:
            return
        self._context.add(event.t, event)
        self._trigger.on_context(event, level)

    def due(self, now: float) -> bool:
        return bool(self._transcript) and self._trigger.due(now)

    def request(self, now: float, state: RiskState | None) -> LLMRequest:
        self._transcript.prune(now)
        self._context.prune(now)
        segments = list(self._transcript)
        self._trigger.started(now)
        return LLMRequest(
            t=now,
            lines=MappingProxyType({segment.seg_id: segment for segment in segments}),
            prompt=build_user_prompt(segments, list(self._context), state),
        )

    def execute(self, request: LLMRequest) -> LLMOutcome:
        call = assess(self._chat, SYSTEM_PROMPT, request.prompt)
        guard = None
        if call.reply is not None:
            guard = apply_guard(
                call.reply,
                request.lines,
                t_available=request.t + call.latency_s,
                min_overlap=self._config.llm.evidence_min_overlap,
                compliance_confidence=self._config.signals.digit_confidence,
            )
        return LLMOutcome(t_request=request.t, call=call, guard=guard)

    def finish(self, outcome: LLMOutcome) -> None:
        del outcome  # nothing to merge yet; the session feeds the signals to the engine
        self._trigger.finished()

    def reset(self) -> None:
        """Session end: forget the transcript window and any pending trigger."""
        self._transcript.clear()
        self._context.clear()
        self._trigger.reset()
