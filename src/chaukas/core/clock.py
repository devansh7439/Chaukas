"""Session clocks.

Every timestamp in Chaukas is seconds since session start. Live mode reads a monotonic
clock; replay and evaluation drive a virtual clock, so the same engine code runs in both.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from chaukas.core.errors import ClockError


@runtime_checkable
class Clock(Protocol):
    """Anything that can tell the current session time."""

    def now(self) -> float:
        """Seconds since session start."""
        ...


class MonotonicClock:
    """Real time from a monotonic source, rebased so the session starts at 0.

    Monotonic time doesn't jump when the wall clock changes, so durations stay correct.
    Safe to read from any thread.
    """

    __slots__ = ("_origin", "_source")

    def __init__(self, source: Callable[[], float] = time.monotonic) -> None:
        self._source = source
        self._origin = source()

    def now(self) -> float:
        return self._source() - self._origin

    def restart(self) -> None:
        """Start a new session at time 0."""
        self._origin = self._source()


class VirtualClock:
    """A clock that moves only when told to; used by replay and the evaluation engine pass.

    It never moves backwards, which keeps simulated event order consistent.
    Not thread-safe: drive it from one thread.
    """

    __slots__ = ("_now",)

    def __init__(self, start: float = 0.0) -> None:
        _check_time("start", start)
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def advance_to(self, t: float) -> None:
        """Move to time ``t``, which must not be earlier than now."""
        _check_time("t", t)
        if t < self._now:
            raise ClockError(f"cannot move the clock back from {self._now} to {t}")
        self._now = float(t)

    def advance_by(self, dt: float) -> None:
        """Move forward by ``dt`` seconds."""
        _check_time("dt", dt)
        self._now += dt


def _check_time(name: str, value: float) -> None:
    if not (math.isfinite(value) and value >= 0.0):
        raise ClockError(f"{name} must be a finite, non-negative number, got {value!r}")
