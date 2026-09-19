"""Level hysteresis and user dismissal.

Escalation is immediate. De-escalation waits until the score has stayed clearly below the
current level's threshold (threshold - margin) for ``hysteresis_hold_s``, so an alert
doesn't flicker as evidence arrives in bursts. A dismissal ("I understand, continue") quiets
the current level for ``dismissal_s``, unless something new happens in the meantime.
"""

from __future__ import annotations

from dataclasses import dataclass

from chaukas.core.config import RulesConfig, ThresholdsConfig
from chaukas.core.models import Level


@dataclass(frozen=True, slots=True)
class _Dismissal:
    level: Level
    until: float
    change_marker: int


class LevelController:
    """Turns each evaluation's raw level into the level that is shown."""

    __slots__ = ("_below_since", "_dismissal", "_level", "_rules", "_thresholds")

    def __init__(self, thresholds: ThresholdsConfig, rules: RulesConfig) -> None:
        self._thresholds = thresholds
        self._rules = rules
        self._level = Level.QUIET
        self._below_since: float | None = None
        self._dismissal: _Dismissal | None = None

    @property
    def level(self) -> Level:
        return self._level

    def update(self, now: float, raw: Level, score: float) -> Level:
        """Feed one evaluation; return the level to show."""
        if raw >= self._level:
            self._level = raw
            self._below_since = None
            return self._level
        if score >= self._threshold(self._level) - self._rules.hysteresis_margin:
            self._below_since = None  # not clearly below: restart the hold
            return self._level
        if self._below_since is None:
            self._below_since = now
        if now - self._below_since >= self._rules.hysteresis_hold_s:
            self._level = raw
            self._below_since = None
        return self._level

    def dismiss(self, now: float, change_marker: int) -> None:
        """The user acknowledged the current level. ``change_marker`` identifies what they saw."""
        if self._level is Level.QUIET:
            return
        self._dismissal = _Dismissal(self._level, now + self._rules.dismissal_s, change_marker)

    def is_dismissed(self, now: float, change_marker: int) -> bool:
        """True while the shown level is the one dismissed, in time, with nothing new since."""
        dismissal = self._dismissal
        return (
            dismissal is not None
            and dismissal.level is self._level
            and now < dismissal.until
            and dismissal.change_marker == change_marker
        )

    def reset(self) -> None:
        self._level = Level.QUIET
        self._below_since = None
        self._dismissal = None

    def _threshold(self, level: Level) -> float:
        thresholds = self._thresholds
        if level is Level.QUIET:
            return 0.0
        if level is Level.NOTICE:
            return thresholds.notice
        if level is Level.WARNING:
            return thresholds.warning
        return thresholds.critical  # critical and critical_recovery
