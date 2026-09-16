"""A time-ordered priority queue for discrete-event simulation.

Replay and the evaluation engine pass merge several sources (speech segments, context
events, LLM results that land after a measured latency) into one timeline and process
them in time order. A binary heap gives O(log n) push and pop. A monotonically increasing
sequence number breaks ties by insertion order, so equal timestamps replay deterministically
and items themselves never need to be comparable.
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Iterator
from typing import Generic, TypeVar

T = TypeVar("T")


class Timeline(Generic[T]):
    """Min-heap of ``(time, item)`` with stable ordering for equal times."""

    __slots__ = ("_heap", "_seq")

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, T]] = []
        self._seq = itertools.count()

    def push(self, t: float, item: T) -> None:
        """Schedule ``item`` at time ``t``. O(log n)."""
        if not math.isfinite(t):
            raise ValueError(f"time must be finite, got {t!r}")
        heapq.heappush(self._heap, (t, next(self._seq), item))

    def pop(self) -> tuple[float, T]:
        """Remove and return the earliest ``(time, item)``. O(log n)."""
        if not self._heap:
            raise IndexError("pop from an empty Timeline")
        t, _, item = heapq.heappop(self._heap)
        return t, item

    def peek_time(self) -> float | None:
        """Time of the earliest item, or None when empty. O(1)."""
        return self._heap[0][0] if self._heap else None

    def drain_until(self, t: float) -> Iterator[tuple[float, T]]:
        """Pop every item due at or before ``t``, in order.

        Items pushed during iteration are included if they are also due by ``t``,
        which is what a discrete-event loop needs when a handler schedules follow-ups.
        """
        while self._heap and self._heap[0][0] <= t:
            yield self.pop()

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
