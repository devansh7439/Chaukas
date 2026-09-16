from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chaukas.core.window import TimeWindow


@pytest.mark.parametrize("bad", [0.0, -5.0, math.nan, math.inf])
def test_rejects_invalid_horizon(bad: float) -> None:
    with pytest.raises(ValueError, match="horizon"):
        TimeWindow[str](bad)


def test_since_returns_items_at_or_after_a_time() -> None:
    window: TimeWindow[str] = TimeWindow(300.0)
    for t, item in [(1.0, "a"), (2.0, "b"), (3.0, "c")]:
        window.add(t, item)
    assert window.since(2.0) == ["b", "c"]
    assert window.since(10.0) == []
    assert window.since(0.0) == ["a", "b", "c"]


def test_late_arrival_is_placed_in_time_order() -> None:
    window: TimeWindow[str] = TimeWindow(300.0)
    window.add(5.0, "user segment")
    window.add(1.0, "long caller segment that finished later")
    window.add(7.0, "next")
    assert list(window.with_times()) == [
        (1.0, "long caller segment that finished later"),
        (5.0, "user segment"),
        (7.0, "next"),
    ]


def test_equal_times_keep_insertion_order() -> None:
    window: TimeWindow[str] = TimeWindow(300.0)
    window.add(2.0, "first")
    window.add(3.0, "later")
    window.add(2.0, "second")
    assert list(window) == ["first", "second", "later"]


def test_prune_keeps_items_exactly_at_the_cutoff() -> None:
    window: TimeWindow[str] = TimeWindow(90.0)
    for t in (0.0, 10.0, 20.0):
        window.add(t, f"t{t:g}")
    assert window.prune(now=100.0) == 1  # cutoff 10.0: drop t0, keep t10
    assert list(window) == ["t10", "t20"]


def test_latest_clear_and_container_protocol() -> None:
    window: TimeWindow[str] = TimeWindow(60.0)
    assert window.latest() is None
    assert not window
    window.add(1.0, "a")
    window.add(4.0, "b")
    assert window.latest() == (4.0, "b")
    assert len(window) == 2
    window.clear()
    assert len(window) == 0
    assert window.latest() is None


def test_rejects_non_finite_time() -> None:
    with pytest.raises(ValueError, match="finite"):
        TimeWindow[str](10.0).add(math.nan, "x")


operations = st.lists(
    st.one_of(
        st.tuples(st.just("add"), st.floats(min_value=0, max_value=1000, allow_nan=False)),
        st.tuples(st.just("prune"), st.floats(min_value=0, max_value=1200, allow_nan=False)),
    ),
    max_size=60,
)


@given(operations)
def test_matches_a_naive_sorted_list(ops: list[tuple[str, float]]) -> None:
    """Model-based check against the simplest correct implementation."""
    horizon = 100.0
    window: TimeWindow[int] = TimeWindow(horizon)
    model: list[tuple[float, int]] = []  # kept stably sorted by time
    for counter, (op, value) in enumerate(ops):
        if op == "add":
            window.add(value, counter)
            model.append((value, counter))
            model.sort(key=lambda pair: pair[0])
        else:
            window.prune(value)
            model = [pair for pair in model if pair[0] >= value - horizon]
        assert list(window.with_times()) == model
