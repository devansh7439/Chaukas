"""A sliding time window: items kept for a fixed horizon, ordered by time.

Chaukas keeps several of these: the last 5 minutes of transcript (the privacy horizon),
the last 90 s for the LLM prompt and the digit rule, and the last 5 minutes of context.

Design: two parallel arrays (times, items) kept sorted by time.

* ``add`` is O(1) when items arrive in time order, which is the normal case. A late
  arrival (a long caller segment that finished after a shorter user segment) is placed
  with binary search; the shift costs O(distance from the end), tiny in practice.
* ``since(t)`` binary-searches the times array: O(log n + k) for k results.
* Eviction deletes the expired prefix immediately rather than advancing an offset, so
  expired transcript text is released at once (a privacy property). The pointer shift is
  O(n), negligible at these sizes: a 5-minute window holds a few hundred segments at most.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from typing import Generic, TypeVar

T = TypeVar("T")


class TimeWindow(Generic[T]):
    """Time-ordered items retained for ``horizon`` seconds."""

    __slots__ = ("_horizon", "_items", "_times")

    def __init__(self, horizon: float) -> None:
        if not (math.isfinite(horizon) and horizon > 0.0):
            raise ValueError(f"horizon must be a positive number of seconds, got {horizon!r}")
        self._horizon = float(horizon)
        self._times: list[float] = []
        self._items: list[T] = []

    @property
    def horizon(self) -> float:
        return self._horizon

    def add(self, t: float, item: T) -> None:
        """Insert ``item`` at time ``t``. Equal times keep insertion order."""
        if not math.isfinite(t):
            raise ValueError(f"time must be finite, got {t!r}")
        if not self._times or t >= self._times[-1]:
            self._times.append(t)
            self._items.append(item)
            return
        i = bisect_right(self._times, t)
        self._times.insert(i, t)
        self._items.insert(i, item)

    def prune(self, now: float) -> int:
        """Drop items older than ``now - horizon``; return how many were dropped."""
        return self.evict_before(now - self._horizon)

    def evict_before(self, cutoff: float) -> int:
        """Drop items with time strictly before ``cutoff``; return how many were dropped."""
        k = bisect_left(self._times, cutoff)
        if k:
            del self._times[:k]
            del self._items[:k]
        return k

    def since(self, t: float) -> list[T]:
        """Items with time >= ``t``, oldest first."""
        return self._items[bisect_left(self._times, t) :]

    def latest(self) -> tuple[float, T] | None:
        """The newest ``(time, item)``, or None when empty."""
        if not self._items:
            return None
        return self._times[-1], self._items[-1]

    def with_times(self) -> Iterator[tuple[float, T]]:
        """Iterate ``(time, item)`` pairs, oldest first."""
        return zip(self._times, self._items, strict=True)

    def clear(self) -> None:
        """Drop everything (session wipe)."""
        self._times.clear()
        self._items.clear()

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)
