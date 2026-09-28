"""Tactic evidence with exponential decay in call time.

The evidence ``e_t`` for a kind is its strongest signal after decay:
``confidence * 0.5 ** (age / half_life)``, with age measured on the ActivityClock.

Entries are kept per kind rather than as a single running maximum, because the bounded
LLM discount must be able to lower specific keyword signals after the fact. Entries that
have decayed below ``floor`` are pruned, which bounds memory for long calls; their raw
confidence is folded into a per-kind session peak first, so "seen this session" survives,
and the signal that set that peak is kept too, so the Why panel can still quote it.
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

    __slots__ = ("_clock", "_entries", "_first_seen", "_floor", "_half_life", "_pruned_peak",
                 "_pruned_signal")  # fmt: skip

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
        self._pruned_signal: dict[SignalKind, Signal] = {}  # the signal behind each peak
        self._first_seen: dict[SignalKind, float] = {}  # session time, survives pruning

    def add(self, signal: Signal) -> None:
        entry = _Entry(signal, signal.confidence, self._clock.call_time(signal.t))
        self._entries[signal.kind].append(entry)
        first = self._first_seen.get(signal.kind)
        if first is None or signal.t < first:
            self._first_seen[signal.kind] = signal.t

    def first_seen(self, kind: SignalKind) -> float | None:
        """Session time of the earliest ``kind`` signal this session, or None."""
        return self._first_seen.get(kind)

    def latest(self, kind: SignalKind, *, min_confidence: float) -> Signal | None:
        """The latest ``kind`` signal that was at least ``min_confidence`` (after discounts),
        among entries not yet pruned; None if there is none. Pruning needs about 5.6
        half-lives of speech even for a 0.5 signal, so this is exact for any look-back
        shorter than that."""
        qualifying = [
            e.signal for e in self._entries.get(kind, ()) if e.confidence >= min_confidence
        ]
        return max(qualifying, key=lambda s: s.t, default=None)

    def level(self, kind: SignalKind, now: float, *, min_confidence: float = 0.0) -> float:
        """Decayed evidence for ``kind`` at session time ``now``, counting only signals that
        were at least ``min_confidence`` when heard."""
        now_call = self._clock.call_time(now)
        return max(
            (
                self._decayed(e, now_call)
                for e in self._entries.get(kind, ())
                if e.confidence >= min_confidence
            ),
            default=0.0,
        )

    def strongest(
        self, kind: SignalKind, now: float, *, min_confidence: float = 0.0
    ) -> Signal | None:
        """The signal currently contributing ``level(kind, now, min_confidence=...)``:
        among signals at least ``min_confidence`` when heard, the strongest after decay."""
        now_call = self._clock.call_time(now)
        qualifying = [e for e in self._entries.get(kind, ()) if e.confidence >= min_confidence]
        if not qualifying:
            return None
        return max(qualifying, key=lambda e: self._decayed(e, now_call)).signal

    def explanation(self, kind: SignalKind, now: float, *, min_confidence: float) -> Signal | None:
        """The signal to show for ``kind`` in the Why panel: the strongest one that was at
        least ``min_confidence`` when heard, even if it has since decayed and been pruned.
        A weaker signal heard later never stands in for it."""
        live = self.strongest(kind, now, min_confidence=min_confidence)
        if live is not None:
            return live
        pruned = self._pruned_signal.get(kind)
        if pruned is not None and self._pruned_peak.get(kind, 0.0) >= min_confidence:
            return pruned
        return None

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
                elif entry.confidence >= self._pruned_peak.get(kind, 0.0):
                    self._pruned_peak[kind] = entry.confidence
                    self._pruned_signal[kind] = entry.signal
            entries[:] = kept

    def reset(self) -> None:
        self._entries.clear()
        self._pruned_peak.clear()
        self._pruned_signal.clear()
        self._first_seen.clear()

    def _decayed(self, entry: _Entry, now_call: float) -> float:
        age = max(0.0, now_call - entry.call_t)
        return entry.confidence * math.pow(0.5, age / self._half_life)
