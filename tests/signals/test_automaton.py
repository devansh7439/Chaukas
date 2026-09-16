from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chaukas.signals.automaton import Match, TokenAutomaton


def build(patterns: dict[str, str]) -> TokenAutomaton[str]:
    automaton: TokenAutomaton[str] = TokenAutomaton()
    for text, payload in patterns.items():
        automaton.add(text.split(), payload)
    return automaton.build()


def test_finds_multi_word_patterns_with_token_boundaries() -> None:
    automaton = build({"digital arrest": "surveillance", "arrest": "threat"})
    tokens = ["you", "are", "under", "digital", "arrest", "not", "arrested"]
    assert automaton.find(tokens) == [
        Match(3, 5, "surveillance"),
        Match(4, 5, "threat"),
    ]


def test_failure_links_recover_overlapping_candidates() -> None:
    automaton = build({"a b c": "abc", "b a b": "bab", "b c": "bc"})
    found = {(m.start, m.end, m.payload) for m in automaton.find(["a", "b", "a", "b", "c"])}
    assert found == {(1, 4, "bab"), (2, 5, "abc"), (3, 5, "bc")}


def test_same_pattern_with_several_payloads() -> None:
    automaton: TokenAutomaton[str] = TokenAutomaton()
    automaton.add(["otp"], "keyword")
    automaton.add(["otp"], "object")
    automaton.build()
    assert {m.payload for m in automaton.find(["otp"])} == {"keyword", "object"}
    assert len(automaton) == 2


def test_lifecycle_errors() -> None:
    automaton: TokenAutomaton[str] = TokenAutomaton()
    with pytest.raises(ValueError, match="at least one token"):
        automaton.add([], "x")
    with pytest.raises(RuntimeError, match="build"):
        automaton.find(["x"])
    automaton.add(["x"], "x")
    automaton.build()
    assert automaton.build() is automaton  # idempotent
    with pytest.raises(RuntimeError, match="after build"):
        automaton.add(["y"], "y")


def naive_find(patterns: list[list[str]], tokens: list[str]) -> set[tuple[int, int, int]]:
    found = set()
    for index, pattern in enumerate(patterns):
        for start in range(len(tokens) - len(pattern) + 1):
            if tokens[start : start + len(pattern)] == pattern:
                found.add((start, start + len(pattern), index))
    return found


small_tokens = st.lists(st.sampled_from(["a", "b", "c"]), min_size=1, max_size=4)


@given(
    st.lists(small_tokens, min_size=1, max_size=8), st.lists(st.sampled_from("abc"), max_size=30)
)
def test_matches_naive_search(patterns: list[list[str]], tokens: list[str]) -> None:
    automaton: TokenAutomaton[int] = TokenAutomaton()
    for index, pattern in enumerate(patterns):
        automaton.add(pattern, index)
    automaton.build()
    found = {(m.start, m.end, m.payload) for m in automaton.find(tokens)}
    assert found == naive_find(patterns, tokens)
