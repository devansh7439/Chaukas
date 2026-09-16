"""Aho–Corasick automaton over token sequences.

Finds every occurrence of every pattern (a sequence of tokens) in one left-to-right pass:
O(n + z) for n tokens and z matches, after an O(total pattern length) build. The lexicon,
request verbs and objects, and suppression phrases are all compiled into automata and
scanned on every segment.

Matching is on whole tokens, which gives word boundaries for free, including for
Devanagari words that ``\\b`` in regular expressions handles incorrectly.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Self, TypeVar

P = TypeVar("P")


@dataclass(frozen=True, slots=True)
class Match(Generic[P]):
    """One pattern occurrence: tokens ``[start, end)`` and the pattern's payload."""

    start: int
    end: int
    payload: P


class TokenAutomaton(Generic[P]):
    """Add patterns, call ``build()`` once, then ``find()`` as often as needed."""

    __slots__ = ("_built", "_fail", "_goto", "_out", "_patterns")

    def __init__(self) -> None:
        self._goto: list[dict[str, int]] = [{}]  # node -> token -> child node; node 0 is root
        self._fail: list[int] = [0]  # longest proper suffix that is also a trie path
        self._out: list[list[tuple[int, P]]] = [[]]  # (pattern length, payload) ending here
        self._patterns = 0
        self._built = False

    def add(self, pattern: Sequence[str], payload: P) -> None:
        """Register ``pattern``. The same pattern may be added with several payloads."""
        if self._built:
            raise RuntimeError("cannot add patterns after build()")
        if not pattern:
            raise ValueError("pattern must contain at least one token")
        node = 0
        for token in pattern:
            child = self._goto[node].get(token)
            if child is None:
                child = len(self._goto)
                self._goto.append({})
                self._fail.append(0)
                self._out.append([])
                self._goto[node][token] = child
            node = child
        self._out[node].append((len(pattern), payload))
        self._patterns += 1

    def build(self) -> Self:
        """Compute failure links breadth-first and merge suffix outputs."""
        if self._built:
            return self
        queue = deque(self._goto[0].values())  # depth-1 nodes fail to the root
        while queue:
            node = queue.popleft()
            for token, child in self._goto[node].items():
                queue.append(child)
                fallback = self._fail[node]
                while fallback and token not in self._goto[fallback]:
                    fallback = self._fail[fallback]
                self._fail[child] = self._goto[fallback].get(token, 0)
                # BFS order guarantees the failure target's outputs are already merged.
                self._out[child] = self._out[child] + self._out[self._fail[child]]
        self._built = True
        return self

    def find(self, tokens: Sequence[str]) -> list[Match[P]]:
        """All matches, ordered by end position, longest first for equal ends."""
        if not self._built:
            raise RuntimeError("call build() before find()")
        matches: list[Match[P]] = []
        node = 0
        for index, token in enumerate(tokens):
            while node and token not in self._goto[node]:
                node = self._fail[node]
            node = self._goto[node].get(token, 0)
            for length, payload in self._out[node]:
                matches.append(Match(index - length + 1, index + 1, payload))
        return matches

    def __len__(self) -> int:
        return self._patterns
