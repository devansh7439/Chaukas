"""Replay event files (blueprint 5.2): ``eval/events/<case>.jsonl``.

One JSON object per line, ``{"t": 52.0, "kind": "bank_page", "detail": "..."}``. Replay
feeds these into the pipeline exactly as the live monitor would, so demos and evaluation
run without real apps. Harm times are labels, never events.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from chaukas.core.errors import ConfigError
from chaukas.core.models import ContextEvent, ContextKind


def read_events(path: Path) -> list[ContextEvent]:
    """Events in time order. Errors name the file and line."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read event file {path}: {exc}") from exc
    events: list[ContextEvent] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            events.append(
                ContextEvent(
                    t=float(record["t"]),
                    kind=ContextKind(record["kind"]),
                    detail=str(record.get("detail", "")),
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"{path}:{number}: invalid event: {exc}") from exc
    return sorted(events, key=lambda event: event.t)


def write_events(path: Path, events: Iterable[ContextEvent]) -> None:
    lines = [
        json.dumps({"t": event.t, "kind": event.kind.value, "detail": event.detail},
                   ensure_ascii=False)
        for event in sorted(events, key=lambda event: event.t)
    ]  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
