from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chaukas.engine.activity import ActivityClock


def test_call_time_counts_only_speech() -> None:
    clock = ActivityClock()
    clock.add(0.0, 2.0)
    clock.add(10.0, 15.0)
    assert [clock.call_time(t) for t in (0.0, 1.0, 2.0, 5.0, 12.0, 100.0)] == [
        0.0,
        1.0,
        2.0,
        2.0,
        4.0,
        7.0,
    ]


def test_overlapping_and_touching_intervals_merge() -> None:
    clock = ActivityClock()
    clock.add(0.0, 2.0)
    clock.add(1.0, 3.0)
    clock.add(3.0, 4.0)
    assert clock.intervals == [(0.0, 4.0)]


def test_a_late_interval_can_bridge_earlier_ones() -> None:
    clock = ActivityClock()
    for start in (0.0, 5.0, 10.0):
        clock.add(start, start + 1.0)
    clock.add(0.5, 10.5)
    assert clock.intervals == [(0.0, 11.0)]
    assert clock.call_time(11.0) == 11.0


def test_out_of_order_insert_keeps_prefix_sums_correct() -> None:
    clock = ActivityClock()
    clock.add(10.0, 12.0)
    clock.add(0.0, 1.0)
    assert clock.call_time(11.0) == 2.0
    assert clock.call_time(50.0) == 3.0


def test_zero_length_is_ignored_and_invalid_intervals_are_rejected() -> None:
    clock = ActivityClock()
    clock.add(3.0, 3.0)
    assert clock.intervals == []
    for start, end in [(5.0, 4.0), (-1.0, 1.0), (0.0, math.inf), (math.nan, 1.0)]:
        with pytest.raises(ValueError, match="invalid interval"):
            clock.add(start, end)


def test_reset() -> None:
    clock = ActivityClock()
    clock.add(0.0, 5.0)
    clock.reset()
    assert clock.call_time(10.0) == 0.0
    clock.add(1.0, 2.0)
    assert clock.call_time(10.0) == 1.0


def naive_union_until(spans: list[tuple[float, float]], t: float) -> float:
    clipped = sorted((s, min(e, t)) for s, e in spans if s < t and e > s)
    total, current = 0.0, None
    for start, end in clipped:
        if current is None or start > current[1]:
            if current is not None:
                total += current[1] - current[0]
            current = (start, end)
        else:
            current = (current[0], max(current[1], end))
    if current is not None:
        total += current[1] - current[0]
    return total


@given(
    st.lists(st.tuples(st.floats(0, 100), st.floats(0, 20)), max_size=25),
    st.floats(0, 130),
)
def test_matches_a_naive_union(pairs: list[tuple[float, float]], t: float) -> None:
    clock = ActivityClock()
    spans = [(start, start + length) for start, length in pairs]
    for start, end in spans:
        clock.add(start, end)
    assert clock.call_time(t) == pytest.approx(naive_union_until(spans, t), abs=1e-9)
