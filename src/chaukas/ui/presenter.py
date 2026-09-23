"""Engine state -> what the dashboard shows. Pure functions, no Qt, fully testable.

Every value handed to QML is a plain dict / list / str / number with camelCase keys, so
the QML side never interprets engine types itself.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Final

from chaukas.core.models import ChainState, Level, Objective, Reason, RiskState, SignalKind
from chaukas.engine.templates import ChainTemplate
from chaukas.ui.copy import Language, text
from chaukas.ui.live import TranscriptEntry

View = dict[str, Any]

_SIGNAL_ICONS: Final[Mapping[str, str]] = {
    "authority": "shield-alert",
    "threat": "triangle-alert",
    "urgency": "clock",
    "isolation": "mic-off",
    "surveillance": "eye",
    "money_request": "send-horizontal",
    "remote_access_request": "monitor",
    "credential_request": "lock",
    "user_digits_spoken": "mic",
}
_CONTEXT_ICON: Final = "monitor"


def clock(t: float) -> str:
    """Seconds as ``MM:SS`` (minutes keep counting past 59)."""
    whole = max(0, int(t))
    return f"{whole // 60:02d}:{whole % 60:02d}"


def present(
    state: RiskState,
    *,
    templates: Sequence[ChainTemplate],
    language: Language,
    paused: bool,
) -> View:
    """The dashboard's main view model for one engine state."""
    level = state.level.label
    components = state.components
    pressure = components.pressure if components is not None else 0.0
    alerting = state.level > Level.QUIET
    return {
        "level": level,
        "levelTitle": text(f"title_{level}", language),
        "headline": text(f"headline_{level}", language),
        "statusLine": text("status_paused" if paused else "status_listening", language),
        "paused": paused,
        "objective": _objective_text(state.objective, state.level, language),
        "objectiveKey": state.objective.value,
        "scorePercent": _percent(state.score),
        "pressurePercent": _percent(pressure),
        "coercion": state.coercion,
        "dismissed": state.dismissed,
        "alertVisible": alerting and not state.dismissed and not paused,
        "callTime": clock(state.t),
        "reasons": [reason_view(reason, language) for reason in state.reasons],
        "chips": evidence_chips(dict(state.evidence), language),
        "chain": chain_view(state.chain, templates, language),
        "fact": _fact(state.objective, state.level, language),
        "ignoreWarning": text("ignore_warning", language),
    }


def reason_view(reason: Reason, language: Language) -> View:
    is_signal = reason.label in _SIGNAL_ICONS
    return {
        "time": clock(reason.t),
        "kind": reason.label,
        "text": text(f"reason_{reason.label}", language, fallback=reason.label),
        "quote": reason.detail,
        "icon": _SIGNAL_ICONS.get(reason.label, _CONTEXT_ICON) if is_signal else _CONTEXT_ICON,
    }


def chain_view(
    chain: ChainState | None, templates: Sequence[ChainTemplate], language: Language
) -> View:
    template = next((t for t in templates if chain and t.name == chain.template), None)
    if chain is None or template is None:
        return {"name": text("chain_none", language), "seen": 0, "total": 0, "steps": [],
                "stepsText": ""}  # fmt: skip
    seen_ids = {step_id for step_id, _ in chain.steps_seen}
    steps = [
        {
            "label": text(f"step_{step.id}", language, fallback=step.id.replace("_", " ")),
            "seen": step.id in seen_ids,
        }
        for step in template.steps
    ]
    seen = sum(1 for step in template.steps if step.id in seen_ids)
    return {
        "name": text(f"chain_{template.name}", language, fallback=template.name),
        "seen": seen,
        "total": len(steps),
        "steps": steps,
        "stepsText": text("steps_of", language).format(seen=seen, total=len(steps)),
    }


def evidence_chips(
    evidence: Mapping[SignalKind, float], language: Language, *, limit: int = 3
) -> list[View]:
    """The strongest current tactics, strongest first."""
    ranked = sorted(
        ((kind, value) for kind, value in evidence.items() if value > 0.0),
        key=lambda item: (-item[1], item[0].value),
    )
    return [
        {"kind": kind.value, "label": text(f"kind_{kind.value}", language),
         "percent": _percent(value)}
        for kind, value in ranked[:limit]
    ]  # fmt: skip


def transcript_view(entries: Sequence[TranscriptEntry], language: Language) -> list[View]:
    """The call log: caller and user lines with their tactic tags, and screen events."""
    views: list[View] = []
    for entry in entries:
        if entry.speaker == "system":
            kind = entry.kinds[0] if entry.kinds else ""
            views.append({"speaker": "system", "time": clock(entry.t),
                          "text": text(f"reason_{kind}", language, fallback=kind),
                          "detail": entry.text, "tags": []})  # fmt: skip
            continue
        views.append(
            {
                "speaker": entry.speaker,
                "time": clock(entry.t),
                "text": entry.text,
                "detail": "",
                "tags": [text(f"kind_{kind}", language, fallback=kind) for kind in entry.kinds],
            }
        )
    return views


def history_bars(
    points: Sequence[tuple[float, float]], *, now: float, window_s: float, bars: int
) -> list[float]:
    """Peak score in each of ``bars`` equal buckets covering the last ``window_s``."""
    values = [0.0] * bars
    start = now - window_s
    width = window_s / bars
    for t, score in points:
        if t < start or t > now:
            continue
        index = min(bars - 1, int((t - start) / width))
        values[index] = max(values[index], score)
    return values


def _objective_text(objective: Objective, level: Level, language: Language) -> str:
    if objective is Objective.NONE or (objective is Objective.UNCLEAR and level is Level.QUIET):
        return text("objective_none", language)
    return text(f"objective_{objective.value}", language)


def _fact(objective: Objective, level: Level, language: Language) -> str:
    if level is Level.CRITICAL_RECOVERY:
        return text("fact_recovery", language)
    key = {
        Objective.MONEY_TRANSFER: "fact_money",
        Objective.CREDENTIAL_DISCLOSURE: "fact_credential",
        Objective.REMOTE_CONTROL: "fact_remote",
    }.get(objective)
    return text(key, language) if key else ""


def _percent(value: float) -> int:
    return max(0, min(100, math.floor(value * 100 + 0.5)))
