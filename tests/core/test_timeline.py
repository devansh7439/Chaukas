from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chaukas.core.timeline import Timeline


def test_pops_in_time_order() -> None:
    timeline: Timeline[str] = Timeline()
    for t, item in [(3.0, "c"), (1.0, "a"), (2.0, "b")]:
        timeline.push(t, item)
    assert [timeline.pop() for _ in range(3)] == [(1.0, "a"), (2.0, "b"), (3.0, "c")]


def test_equal_times_keep_insertion_order_without_comparing_items() -> None:
    timeline: Timeline[dict[str, int]] = Timeline()
    first, second = {"n": 1}, {"n": 2}  # dicts are not orderable
    timeline.push(5.0, first)
    timeline.push(5.0, second)
    assert timeline.pop()[1] is first
    assert timeline.pop()[1] is second


def test_drain_until_includes_items_scheduled_during_iteration() -> None:
    timeline: Timeline[str] = Timeline()
    timeline.push(1.0, "segment")
    timeline.push(9.0, "late")
    seen = []
    for t, item in timeline.drain_until(5.0):
        seen.append(item)
        if item == "segment":
            timeline.push(t + 2.0, "llm_result")  # due at 3.0, still before the cutoff
    assert seen == ["segment", "llm_result"]
    assert timeline.peek_time() == 9.0
    assert len(timeline) == 1


def test_empty_behaviour() -> None:
    timeline: Timeline[str] = Timeline()
    assert not timeline
    assert timeline.peek_time() is None
    with pytest.raises(IndexError):
        timeline.pop()


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_rejects_non_finite_times(bad: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        Timeline[str]().push(bad, "x")


@given(st.lists(st.floats(min_value=0, max_value=1e6, allow_nan=False)))
def test_pop_order_is_a_stable_sort_by_time(times: list[float]) -> None:
    timeline: Timeline[int] = Timeline()
    for index, t in enumerate(times):
        timeline.push(t, index)
    popped = [timeline.pop() for _ in range(len(times))]
    expected = sorted(((t, index) for index, t in enumerate(times)), key=lambda p: p[0])
    assert popped == expected
