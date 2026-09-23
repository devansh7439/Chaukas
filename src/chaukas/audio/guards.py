"""Guards that keep audio Chaukas shouldn't hear from becoming evidence (blueprint 6.1).

* ``PlaybackGuard``: while Chaukas plays a spoken alert, and for a short tail after, caller
  audio (which would contain the alert, through loopback) is discarded.
* ``EchoGuard``: without headphones the microphone also hears the caller. A user segment
  that overlaps a caller segment in time and repeats most of its words is the caller's
  echo, not the user speaking.
"""

from __future__ import annotations

from typing import Final

from chaukas.core.window import TimeWindow
from chaukas.signals.normalise import tokenize

_ECHO_MEMORY_S: Final = 60.0
_OVERLAP_SLACK_S: Final = 0.5


class PlaybackGuard:
    __slots__ = ("_intervals", "_tail")

    def __init__(self, tail_s: float) -> None:
        self._tail = tail_s
        self._intervals: list[tuple[float, float]] = []

    def playing(self, start: float, end: float) -> None:
        """An alert clip plays during ``[start, end]``."""
        self._intervals = [(s, e) for s, e in self._intervals if e + self._tail >= start]
        self._intervals.append((start, end))

    def muted(self, t: float) -> bool:
        return any(start <= t < end + self._tail for start, end in self._intervals)


class EchoGuard:
    __slots__ = ("_caller", "_similarity")

    def __init__(self, similarity: float) -> None:
        self._similarity = similarity
        self._caller: TimeWindow[tuple[float, frozenset[str]]] = TimeWindow(_ECHO_MEMORY_S)

    def caller_said(self, t_start: float, t_end: float, text: str) -> None:
        self._caller.add(t_start, (t_end, frozenset(tokenize(text))))
        self._caller.prune(t_end)

    def is_echo(self, t_start: float, t_end: float, text: str) -> bool:
        words = tokenize(text)
        if not words:
            return False
        for caller_start, (caller_end, caller_words) in self._caller.with_times():
            overlaps = (
                t_start < caller_end + _OVERLAP_SLACK_S and caller_start < t_end + _OVERLAP_SLACK_S
            )
            if overlaps:
                shared = sum(word in caller_words for word in words) / len(words)
                if shared >= self._similarity:
                    return True
        return False

    def reset(self) -> None:
        self._caller.clear()
