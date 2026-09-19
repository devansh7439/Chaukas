"""Attack-chain matching (blueprint 6.6).

Every template is tracked in parallel. A step is seen at the earliest segment time at which
a listed caller signal (confidence >= ``step_min_confidence``) or a listed context event
occurred; an LLM signal that arrives late but quotes earlier speech moves that time back.
Steps don't decay within a session: the session boundary is the reset.

    progress = seen step weight / total weight
               x order_penalty      if steps appeared noticeably out of template order
               capped at required_step_cap while any required step is unseen
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from chaukas.core.config import ChainConfig
from chaukas.core.models import ChainState, ContextEvent, Objective, Signal, Stream
from chaukas.engine.templates import ChainTemplate, Step


class ChainTracker:
    """First-seen times per template step, and the chain states derived from them."""

    __slots__ = ("_config", "_first_seen", "_templates")

    def __init__(self, templates: Sequence[ChainTemplate], config: ChainConfig) -> None:
        if not templates:
            raise ValueError("at least one chain template is required")
        self._templates = tuple(templates)
        self._config = config
        self._first_seen: tuple[dict[str, float], ...] = tuple({} for _ in self._templates)

    @property
    def templates(self) -> tuple[ChainTemplate, ...]:
        return self._templates

    def observe_signal(self, signal: Signal) -> bool:
        """Record a signal. Returns True if a step became seen for the first time."""
        if signal.speaker is not Stream.CALLER:
            return False
        if signal.confidence < self._config.step_min_confidence:
            return False
        return self._observe(signal.t, lambda step: signal.kind in step.signals)

    def observe_context(self, event: ContextEvent) -> bool:
        """Record a context event. Returns True if a step became seen for the first time."""
        return self._observe(event.t, lambda step: event.kind in step.events)

    def states(self) -> tuple[ChainState, ...]:
        """One state per template, in template order."""
        return tuple(
            self._state(template, seen)
            for template, seen in zip(self._templates, self._first_seen, strict=True)
        )

    def active(self, hint: Objective | None = None) -> ChainState | None:
        """The template that best explains the evidence, or None if no step has been seen.

        Candidates are templates within ``tie_margin`` of the best progress. Among them,
        prefer one with a distinctive step seen, then one whose objective matches ``hint``
        (the LLM's suspected objective), then higher progress, then template order.
        """
        states = self.states()
        best = max(state.progress for state in states)
        if best == 0.0:
            return None
        candidates = [
            (index, state)
            for index, state in enumerate(states)
            if best - state.progress <= self._config.tie_margin
        ]
        _, chosen = min(
            candidates,
            key=lambda item: (
                not item[1].distinctive_seen,
                item[1].objective is not hint,
                -item[1].progress,
                item[0],
            ),
        )
        return chosen

    def reset(self) -> None:
        for seen in self._first_seen:
            seen.clear()

    def _observe(self, t: float, matches: Callable[[Step], bool]) -> bool:
        new_step = False
        for template, seen in zip(self._templates, self._first_seen, strict=True):
            for step in template.steps:
                if not matches(step):
                    continue
                previous = seen.get(step.id)
                if previous is None:
                    seen[step.id] = t
                    new_step = True
                elif t < previous:
                    seen[step.id] = t
        return new_step

    def _state(self, template: ChainTemplate, seen: dict[str, float]) -> ChainState:
        seen_steps = [step for step in template.steps if step.id in seen]  # template order
        progress = sum(step.weight for step in seen_steps) / template.total_weight
        order_score = _order_score([seen[step.id] for step in seen_steps])
        if order_score < self._config.order_penalty_threshold:
            progress *= self._config.order_penalty
        required_seen = all(step.id in seen for step in template.steps if step.required)
        if not required_seen:
            progress = min(progress, self._config.required_step_cap)
        return ChainState(
            template=template.name,
            objective=template.objective,
            progress=min(progress, 1.0),
            order_score=order_score,
            steps_seen=tuple(sorted(seen.items(), key=lambda item: item[1])),
            required_seen=required_seen,
            distinctive_seen=any(step.distinctive for step in seen_steps),
        )


def _order_score(times: Sequence[float]) -> float:
    """Fraction of step pairs, taken in template order, whose times are also in order.

    Ties count as in order. With fewer than two steps there is nothing to compare: 1.0.
    O(k^2) for k seen steps; templates have at most a handful.
    """
    n = len(times)
    if n < 2:
        return 1.0
    in_order = sum(1 for i in range(n) for j in range(i + 1, n) if times[i] <= times[j])
    return in_order / (n * (n - 1) // 2)
