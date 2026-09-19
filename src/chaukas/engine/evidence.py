"""Tactic evidence with exponential decay in call time.

The evidence ``e_t`` for a kind is its strongest signal after decay:
``confidence * 0.5 ** (age / half_life)``, with age measured on the ActivityClock.

Entries are kept per kind rather than as a single running maximum, because the bounded
LLM discount must be able to lower specific keyword signals after the fact. Entries that
have decayed below ``floor`` are pruned, which bounds memory for long calls; their raw
confidence is folded into a per-kind session peak first, so "seen this session" survives.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass

from chaukas.core.models import Signal, SignalKind, SignalSource
from chaukas.engine.activity import ActivityClock

DEFAULT_FLOOR = 0.01


@dataclass(slots=True)
class _Entry:
    signal: Signal
    confidence: float  # starts at the signal's confidence; the LLM discount may lower it
    call_t: float


class EvidenceStore:
    """Per-kind decaying evidence plus session peaks."""

    __slots__ = ("_clock", "_entries", "_floor", "_half_life", "_pruned_peak")

    def __init__(
        self, half_life_s: float, clock: ActivityClock, floor: float = DEFAULT_FLOOR
    ) -> None:
        if half_life_s <= 0.0:
            raise ValueError(f"half_life_s must be positive, got {half_life_s}")
        self._half_life = half_life_s
        self._clock = clock
        self._floor = floor
        self._entries: defaultdict[SignalKind, list[_Entry]] = defaultdict(list)
        self._pruned_peak: dict[SignalKind, float] = {}

    def add(self, signal: Signal) -> None:
        entry = _Entry(signal, signal.confidence, self._clock.call_time(signal.t))
        self._entries[signal.kind].append(entry)

    def level(self, kind: SignalKind, now: float) -> float:
        """Decayed evidence for ``kind`` at session time ``now``."""
        now_call = self._clock.call_time(now)
        return max((self._decayed(e, now_call) for e in self._entries.get(kind, ())), default=0.0)

    def strongest(self, kind: SignalKind, now: float) -> Signal | None:
        """The signal currently contributing ``level(kind, now)``."""
        now_call = self._clock.call_time(now)
        entries = self._entries.get(kind)
        if not entries:
            return None
        return max(entries, key=lambda e: self._decayed(e, now_call)).signal

    def peak(self, kind: SignalKind) -> float:
        """Highest undecayed confidence seen for ``kind`` this session, after discounts."""
        current = max((e.confidence for e in self._entries.get(kind, ())), default=0.0)
        return max(current, self._pruned_peak.get(kind, 0.0))

    def discount(
        self, kinds: Collection[SignalKind], seg_ids: Collection[int], factor: float
    ) -> int:
        """Multiply keyword entries of ``kinds`` from ``seg_ids`` by ``factor``; return count."""
        if not 0.0 <= factor <= 1.0:
            raise ValueError(f"factor must be in [0, 1], got {factor}")
        changed = 0
        for kind in kinds:
            for entry in self._entries.get(kind, ()):
                signal = entry.signal
                if signal.source is SignalSource.KEYWORD and signal.seg_id in seg_ids:
                    entry.confidence *= factor
                    changed += 1
        return changed

    def prune(self, now: float) -> None:
        """Drop entries that have decayed below the floor."""
        now_call = self._clock.call_time(now)
        for kind, entries in self._entries.items():
            kept = []
            for entry in entries:
                if self._decayed(entry, now_call) >= self._floor:
                    kept.append(entry)
                else:
                    peak = self._pruned_peak.get(kind, 0.0)
                    self._pruned_peak[kind] = max(peak, entry.confidence)
            entries[:] = kept

    def reset(self) -> None:
        self._entries.clear()
        self._pruned_peak.clear()

    def _decayed(self, entry: _Entry, now_call: float) -> float:
        age = max(0.0, now_call - entry.call_t)
        return entry.confidence * math.pow(0.5, age / self._half_life)
