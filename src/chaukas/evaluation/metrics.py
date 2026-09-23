"""Per-case outcomes and aggregate metrics (blueprint 8.4).

Proportions carry a 95% Wilson interval, because a 36-case test split cannot support
tight claims: 18 of 18 attacks detected still only means "82-100%".
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Final

from chaukas.core.models import Level, Objective
from chaukas.evaluation.cases import Category
from chaukas.evaluation.runner import CaseRun

Z_95: Final = 1.959963984540054


@dataclass(frozen=True, slots=True)
class Proportion:
    """A count out of a total, with a Wilson confidence interval."""

    hits: int
    total: int

    @property
    def ratio(self) -> float | None:
        return self.hits / self.total if self.total else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson_interval(self.hits, self.total) if self.total else None

    def __str__(self) -> str:
        if not self.total:
            return "n/a"
        low, high = wilson_interval(self.hits, self.total)
        ratio = self.hits / self.total
        return f"{self.hits}/{self.total} ({ratio:.0%}, 95% CI {low:.0%}-{high:.0%})"


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """How one replayed case scored against its labels."""

    case_id: str
    category: Category
    scenario: str
    max_level: Level
    within_acceptable: bool
    detected: bool | None  # attacks only: reached warning or above
    critical_before_harm: bool | None  # attacks with a harm mark
    false_alarm: bool | None  # benign only: reached warning or above
    warning_latency: float | None  # first warning minus the expected_warning mark
    objective_correct: bool | None
    duration_s: float = 0.0
    llm_calls: int = 0  # model calls, retries included
    llm_valid: int = 0  # calls that returned a usable JSON object
    llm_items: int = 0  # tactics and requested actions in usable replies
    llm_rejected: int = 0  # items the evidence guard dropped


def score_case(run: CaseRun) -> CaseOutcome:
    case = run.case
    max_level = run.max_level
    first_warning = run.first_time_at_least(Level.WARNING)
    first_critical = run.first_time_at_least(Level.CRITICAL)
    is_attack = case.category is Category.ATTACK

    critical_before_harm: bool | None = None
    if is_attack and case.harm_t is not None:
        critical_before_harm = first_critical is not None and first_critical < case.harm_t

    latency: float | None = None
    if first_warning is not None and case.expected_warning_t is not None:
        latency = first_warning - case.expected_warning_t

    objective_correct: bool | None = None
    if case.expectation.objective is not Objective.NONE:
        reached = run.objective_when(max(Level.WARNING, case.expectation.max_level))
        objective_correct = reached is case.expectation.objective

    calls = sum(outcome.call.attempts for outcome in run.llm_outcomes)
    valid = sum(outcome.call.reply is not None for outcome in run.llm_outcomes)
    guards = [outcome.guard for outcome in run.llm_outcomes if outcome.guard is not None]
    return CaseOutcome(
        case_id=case.case_id,
        category=case.category,
        scenario=case.scenario,
        max_level=max_level,
        within_acceptable=max_level in case.expectation.acceptable_levels,
        detected=(first_warning is not None) if is_attack else None,
        critical_before_harm=critical_before_harm,
        false_alarm=(first_warning is not None) if not is_attack else None,
        warning_latency=latency,
        objective_correct=objective_correct,
        duration_s=case.end_time,
        llm_calls=calls,
        llm_valid=valid,
        llm_items=sum(guard.accepted + guard.rejected for guard in guards),
        llm_rejected=sum(guard.rejected for guard in guards),
    )


@dataclass(frozen=True, slots=True)
class Summary:
    """Aggregate metrics over a set of cases."""

    cases: int
    attacks: int
    benign: int
    detection: Proportion
    critical_before_harm: Proportion
    false_alarms: Proportion
    notices_on_benign: Proportion
    objective_accuracy: Proportion
    within_acceptable: Proportion
    warning_latency_median: float | None
    warning_latency_p90: float | None
    llm_json_validity: Proportion = Proportion(0, 0)
    llm_evidence_rejected: Proportion = Proportion(0, 0)
    llm_calls_per_minute_benign: float | None = None  # None when the LLM was never called


def summarise(outcomes: Sequence[CaseOutcome]) -> Summary:
    attacks = [o for o in outcomes if o.category is Category.ATTACK]
    benign = [o for o in outcomes if o.category is Category.BENIGN]
    latencies = sorted(o.warning_latency for o in outcomes if o.warning_latency is not None)
    return Summary(
        cases=len(outcomes),
        attacks=len(attacks),
        benign=len(benign),
        detection=_count(o.detected for o in attacks),
        critical_before_harm=_count(o.critical_before_harm for o in attacks),
        false_alarms=_count(o.false_alarm for o in benign),
        notices_on_benign=_count(
            o.max_level is Level.NOTICE for o in benign if o.false_alarm is False
        ),
        objective_accuracy=_count(o.objective_correct for o in outcomes),
        within_acceptable=_count(o.within_acceptable for o in outcomes),
        warning_latency_median=median(latencies) if latencies else None,
        warning_latency_p90=_percentile(latencies, 0.9),
        llm_json_validity=Proportion(
            hits=sum(o.llm_valid for o in outcomes), total=sum(o.llm_calls for o in outcomes)
        ),
        llm_evidence_rejected=Proportion(
            hits=sum(o.llm_rejected for o in outcomes), total=sum(o.llm_items for o in outcomes)
        ),
        llm_calls_per_minute_benign=_calls_per_minute(benign, outcomes),
    )


def _calls_per_minute(
    benign: Sequence[CaseOutcome], outcomes: Sequence[CaseOutcome]
) -> float | None:
    if not any(o.llm_calls for o in outcomes):
        return None
    minutes = sum(o.duration_s for o in benign) / 60.0
    return sum(o.llm_calls for o in benign) / minutes if minutes > 0 else None


def wilson_interval(hits: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval, which behaves sensibly at 0% and 100% and for small n."""
    if total <= 0:
        raise ValueError("total must be positive")
    if not 0 <= hits <= total:
        raise ValueError(f"hits {hits} outside 0..{total}")
    ratio = hits / total
    denominator = 1.0 + z * z / total
    centre = (ratio + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(ratio * (1 - ratio) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


def _count(flags: Iterable[bool | None]) -> Proportion:
    values = [flag for flag in flags if flag is not None]
    return Proportion(hits=sum(values), total=len(values))


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile of an already sorted sequence."""
    if not values:
        return None
    index = min(len(values) - 1, math.ceil(fraction * len(values)) - 1)
    return values[max(0, index)]
