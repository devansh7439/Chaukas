"""Call time: how long people have actually been speaking.

Evidence decays in call time rather than session time, so a silent hold ("stay on
camera, don't say anything") doesn't erase what the caller said before it.

Speech intervals are kept sorted and merged, with prefix sums of their durations:

* ``call_time(t)`` is a binary search plus one partial interval: O(log n).
* ``add`` is O(log n) plus the cost of rebuilding prefix sums from the insertion point,
  which is O(1) amortised when speech arrives in time order (the normal case).
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right


class ActivityClock:
    """Union of speech intervals from both streams, queried as cumulative call time."""

    __slots__ = ("_ends", "_prefix", "_starts")

    def __init__(self) -> None:
        self._starts: list[float] = []
        self._ends: list[float] = []
        self._prefix: list[float] = [0.0]  # _prefix[i] = total duration of intervals [0, i)

    def add(self, start: float, end: float) -> None:
        """Record speech during ``[start, end]``; overlapping or touching intervals merge."""
        if not (math.isfinite(start) and math.isfinite(end) and 0.0 <= start <= end):
            raise ValueError(f"invalid interval [{start!r}, {end!r}]")
        if start == end:
            return
        lo = bisect_left(self._ends, start)  # first interval ending at or after start
        hi = bisect_right(self._starts, end)  # intervals starting at or before end
        if lo < hi:
            start = min(start, self._starts[lo])
            end = max(end, self._ends[hi - 1])
        self._starts[lo:hi] = [start]
        self._ends[lo:hi] = [end]
        del self._prefix[lo + 1 :]
        for i in range(lo, len(self._starts)):
            self._prefix.append(self._prefix[i] + self._ends[i] - self._starts[i])

    def call_time(self, t: float) -> float:
        """Total speech time in ``[0, t]``."""
        k = bisect_right(self._starts, t)  # intervals that started by t
        if k == 0:
            return 0.0
        return self._prefix[k - 1] + min(self._ends[k - 1], t) - self._starts[k - 1]

    @property
    def intervals(self) -> list[tuple[float, float]]:
        return list(zip(self._starts, self._ends, strict=True))

    def reset(self) -> None:
        self._starts.clear()
        self._ends.clear()
        self._prefix[:] = [0.0]
