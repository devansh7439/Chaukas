"""Human-readable output for replays, evaluation runs and ablation tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from chaukas.core.models import Level, Objective, RiskState
from chaukas.evaluation.metrics import CaseOutcome, Summary
from chaukas.evaluation.runner import CaseRun

_OBJECTIVE_TEXT: Mapping[Objective, str] = {
    Objective.MONEY_TRANSFER: "transfer money",
    Objective.REMOTE_CONTROL: "give control of your computer",
    Objective.CREDENTIAL_DISCLOSURE: "reveal your OTP or password",
    Objective.UNCLEAR: "someone may be pressuring you",
    Objective.NONE: "-",
}


def format_run(run: CaseRun, *, max_reasons: int = 4) -> str:
    """A timeline of level changes with the evidence behind each one."""
    case = run.case
    lines = [
        f"{case.case_id}  {case.scenario}  ({case.category.value}, {case.split.value} split)",
        f"expected at most {case.expectation.max_level.label}"
        f", objective {case.expectation.objective.value}",
        "",
    ]
    for snapshot in run.transitions:
        state = snapshot.state
        lines.append(
            f"[{state.t:7.1f}s] {state.level.label.upper():<18}"
            f" R={state.score:.2f}  {_objective_text(state)}"
        )
        for reason in state.reasons[-max_reasons:]:
            lines.append(f"{'':11}  {reason.t:7.1f}s  {reason.label}: {reason.detail}")
    if not run.transitions:
        lines.append("(stayed quiet)")
    lines.extend(["", f"max level reached: {run.max_level.label}"])
    for name, t in [
        ("first warning", run.first_time_at_least(Level.WARNING)),
        ("first critical", run.first_time_at_least(Level.CRITICAL)),
        ("harm (label)", case.harm_t),
    ]:
        lines.append(f"{name:>15}: {'-' if t is None else f'{t:.1f}s'}")
    return "\n".join(lines)


def format_outcomes(outcomes: Sequence[CaseOutcome], summary: Summary) -> str:
    """One row per case, then the aggregate metrics."""
    header = f"{'case':<8} {'category':<8} {'scenario':<20} {'max level':<18} {'ok':<3} notes"
    lines = [header, "-" * len(header)]
    for outcome in outcomes:
        notes = []
        if outcome.critical_before_harm is not None:
            notes.append(
                "critical before harm" if outcome.critical_before_harm else "CRITICAL TOO LATE"
            )
        if outcome.false_alarm:
            notes.append("false alarm")
        if outcome.warning_latency is not None:
            notes.append(f"latency {outcome.warning_latency:+.1f}s")
        if outcome.objective_correct is False:
            notes.append("wrong objective")
        lines.append(
            f"{outcome.case_id:<8} {outcome.category.value:<8} {outcome.scenario:<20}"
            f" {outcome.max_level.label:<18} {'yes' if outcome.within_acceptable else 'NO':<3}"
            f" {', '.join(notes)}"
        )
    lines.extend(["", format_summary(summary)])
    return "\n".join(lines)


def format_summary(summary: Summary) -> str:
    rows = [
        ("cases", f"{summary.cases} ({summary.attacks} attack, {summary.benign} benign)"),
        ("detection", str(summary.detection)),
        ("critical before harm", str(summary.critical_before_harm)),
        ("false alarms", str(summary.false_alarms)),
        ("notices on benign", str(summary.notices_on_benign)),
        ("objective accuracy", str(summary.objective_accuracy)),
        ("within acceptable", str(summary.within_acceptable)),
        ("warning latency", _latency(summary)),
    ]
    return "\n".join(f"{name:>21}: {value}" for name, value in rows)


def format_ablation(summaries: Mapping[str, Summary]) -> str:
    """The A-E table from blueprint 8.5."""
    width = 28  # a proportion with its confidence interval needs the room
    header = (
        f"{'config':<7} {'detection':<{width}} {'critical before harm':<{width}}"
        f" {'false alarms':<{width}} latency"
    )
    lines = [header, "-" * len(header)]
    for name, summary in summaries.items():
        lines.append(
            f"{name:<7} {summary.detection!s:<{width}} {summary.critical_before_harm!s:<{width}}"
            f" {summary.false_alarms!s:<{width}} {_latency(summary)}"
        )
    return "\n".join(lines)


def format_scripted_llm_note(scripted: Sequence[str], total: int, configs: Sequence[str]) -> str:
    """Say plainly that LLM configurations ran on hand-written verdicts, not a real model."""
    names = configs[0] if len(configs) == 1 else f"{', '.join(configs[:-1])} and {configs[-1]}"
    return (
        f"note: {len(scripted)} of {total} cases script the LLM's verdict"
        f" ({', '.join(scripted)}); results for {names} reflect those scripts, not a real model."
    )


def _latency(summary: Summary) -> str:
    if summary.warning_latency_median is None:
        return "-"
    p90 = summary.warning_latency_p90
    p90_text = "-" if p90 is None else f"{p90:+.1f}s"
    return f"median {summary.warning_latency_median:+.1f}s, p90 {p90_text}"


def _objective_text(state: RiskState) -> str:
    return _OBJECTIVE_TEXT.get(state.objective, state.objective.value)
