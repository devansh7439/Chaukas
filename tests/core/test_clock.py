from __future__ import annotations

import math

import pytest

from chaukas.core.clock import Clock, MonotonicClock, VirtualClock
from chaukas.core.errors import ClockError


class FakeSource:
    def __init__(self, start: float) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


class TestMonotonicClock:
    def test_starts_at_zero_and_tracks_the_source(self) -> None:
        source = FakeSource(1000.0)
        clock = MonotonicClock(source)
        assert clock.now() == 0.0
        source.value = 1012.5
        assert clock.now() == 12.5

    def test_restart_rebases_to_zero(self) -> None:
        source = FakeSource(50.0)
        clock = MonotonicClock(source)
        source.value = 80.0
        clock.restart()
        assert clock.now() == 0.0

    def test_default_source_moves_forward(self) -> None:
        clock = MonotonicClock()
        first = clock.now()
        assert clock.now() >= first >= 0.0


class TestVirtualClock:
    def test_advances_forward(self) -> None:
        clock = VirtualClock()
        clock.advance_to(10.0)
        clock.advance_to(10.0)  # staying put is allowed
        clock.advance_by(2.5)
        assert clock.now() == 12.5

    def test_refuses_to_move_backwards(self) -> None:
        clock = VirtualClock(start=5.0)
        with pytest.raises(ClockError, match="back"):
            clock.advance_to(4.0)

    @pytest.mark.parametrize("bad", [-1.0, math.nan, math.inf])
    def test_rejects_invalid_values(self, bad: float) -> None:
        clock = VirtualClock()
        with pytest.raises(ClockError):
            clock.advance_to(bad)
        with pytest.raises(ClockError):
            clock.advance_by(bad)
        with pytest.raises(ClockError):
            VirtualClock(start=bad)


def test_both_clocks_satisfy_the_protocol() -> None:
    assert isinstance(MonotonicClock(), Clock)
    assert isinstance(VirtualClock(), Clock)
