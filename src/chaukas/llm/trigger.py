"""When to call the LLM (blueprint 6.4).

The LLM is expensive NPU time, so it runs only when there is something to reason about:

* at once after a strong, phrase or fast-path keyword from the caller (weak keywords never
  trigger it, and neither do the LLM's own signals);
* on a context event while an alert is showing (level notice or above);
* on a heartbeat every ``heartbeat_s`` if at least ``heartbeat_min_speech_s`` of new caller
  speech has accumulated, to catch paraphrased attacks the lexicon misses.

At most one call is in flight, and calls start at least ``debounce_s`` apart. Pure logic:
time is passed in, so live mode and replay share it.
"""

from __future__ import annotations

from typing import Final

from chaukas.core.config import LLMConfig
from chaukas.core.models import ContextEvent, Level, Segment, Signal, Stream, Tier

_TRIGGER_TIERS: Final = frozenset({Tier.STRONG, Tier.PHRASE, Tier.FAST_PATH})


class TriggerPolicy:
    __slots__ = ("_config", "_in_flight", "_last_start", "_new_speech_s", "_pending")

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._pending = False
        self._in_flight = False
        self._last_start: float | None = None
        self._new_speech_s = 0.0

    @property
    def in_flight(self) -> bool:
        return self._in_flight

    def on_segment(self, segment: Segment) -> None:
        if segment.stream is Stream.CALLER:
            self._new_speech_s += segment.duration

    def on_signal(self, signal: Signal) -> None:
        if signal.speaker is Stream.CALLER and signal.tier in _TRIGGER_TIERS:
            self._pending = True

    def on_context(self, event: ContextEvent, level: Level) -> None:
        if event.objective is not None and level >= Level.NOTICE:
            self._pending = True

    def due(self, now: float) -> bool:
        """Should a call start at ``now``?"""
        if self._in_flight:
            return False
        last = self._last_start
        if last is not None and now - last < self._config.debounce_s:
            return False
        if self._pending:
            return True
        since = now - (last if last is not None else 0.0)
        return (
            since >= self._config.heartbeat_s
            and self._new_speech_s >= self._config.heartbeat_min_speech_s
        )

    def started(self, now: float) -> None:
        """A call started; it covers everything observed so far."""
        self._in_flight = True
        self._last_start = now
        self._pending = False
        self._new_speech_s = 0.0

    def finished(self) -> None:
        self._in_flight = False

    def reset(self) -> None:
        self._pending = False
        self._in_flight = False
        self._last_start = None
        self._new_speech_s = 0.0
