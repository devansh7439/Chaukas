"""Domain model shared by every layer.

Records that flow through the pipeline (segments, signals, context events) are frozen,
slotted dataclasses: immutable, so they can cross threads without locks, and slotted, so
each instance stays small. Engine outputs (ChainState, RiskState) are immutable snapshots
for the same reason: the engine hands them to the UI thread and to evaluation as-is.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum
from types import MappingProxyType


class Stream(StrEnum):
    """Which audio stream a segment came from."""

    CALLER = "caller"  # system audio (WASAPI loopback)
    USER = "user"  # microphone


class SignalKind(StrEnum):
    """What a signal is evidence of."""

    AUTHORITY = "authority"
    THREAT = "threat"
    URGENCY = "urgency"
    ISOLATION = "isolation"
    SURVEILLANCE = "surveillance"
    MONEY_REQUEST = "money_request"
    REMOTE_ACCESS_REQUEST = "remote_access_request"
    CREDENTIAL_REQUEST = "credential_request"
    USER_DIGITS_SPOKEN = "user_digits_spoken"

    @property
    def is_coercive(self) -> bool:
        """Threat, isolation and surveillance count as coercion; urgency alone does not."""
        return self in _COERCIVE

    @property
    def is_request(self) -> bool:
        """The caller asking for money, remote access or credentials."""
        return self in _REQUESTS


_COERCIVE: frozenset[SignalKind] = frozenset(
    {SignalKind.THREAT, SignalKind.ISOLATION, SignalKind.SURVEILLANCE}
)
_REQUESTS: frozenset[SignalKind] = frozenset(
    {SignalKind.MONEY_REQUEST, SignalKind.REMOTE_ACCESS_REQUEST, SignalKind.CREDENTIAL_REQUEST}
)


class SignalSource(StrEnum):
    """Which detector produced a signal."""

    KEYWORD = "keyword"
    LLM = "llm"
    RULE = "rule"


class Tier(StrEnum):
    """How strongly a detector vouches for a signal; keyword tiers map to starting confidences."""

    WEAK = "weak"
    STRONG = "strong"
    PHRASE = "phrase"
    FAST_PATH = "fast_path"
    LLM = "llm"
    RULE = "rule"


class Objective(StrEnum):
    """What the attacker is suspected of trying to get the user to do."""

    MONEY_TRANSFER = "money_transfer"
    REMOTE_CONTROL = "remote_control"
    CREDENTIAL_DISCLOSURE = "credential_disclosure"
    NONE = "none"
    UNCLEAR = "unclear"


class ContextKind(StrEnum):
    """Something observed on the desktop."""

    REMOTE_APP_STARTED = "remote_app_started"
    BANK_PAGE = "bank_page"
    TRANSFER_PAGE = "transfer_page"
    DOWNLOAD_EXECUTABLE = "download_executable"
    OTP_FIELD_VISIBLE = "otp_field_visible"
    PASSWORD_FIELD_VISIBLE = "password_field_visible"
    WINDOW_CHANGED = "window_changed"

    @property
    def objective(self) -> Objective | None:
        """The objective this context supports, or None if it is not action context."""
        return _CONTEXT_OBJECTIVE.get(self)


_CONTEXT_OBJECTIVE: Mapping[ContextKind, Objective] = MappingProxyType(
    {
        ContextKind.REMOTE_APP_STARTED: Objective.REMOTE_CONTROL,
        ContextKind.DOWNLOAD_EXECUTABLE: Objective.REMOTE_CONTROL,
        ContextKind.BANK_PAGE: Objective.MONEY_TRANSFER,
        ContextKind.TRANSFER_PAGE: Objective.MONEY_TRANSFER,
        ContextKind.OTP_FIELD_VISIBLE: Objective.CREDENTIAL_DISCLOSURE,
        ContextKind.PASSWORD_FIELD_VISIBLE: Objective.CREDENTIAL_DISCLOSURE,
    }
)


class Level(IntEnum):
    """Alert level. The integer values are the escalation order, so levels compare naturally."""

    QUIET = 0
    NOTICE = 1
    WARNING = 2
    CRITICAL = 3
    CRITICAL_RECOVERY = 4

    @property
    def label(self) -> str:
        """Lower-case name used in config, logs and labels.csv."""
        return self.name.lower()

    @classmethod
    def parse(cls, label: str) -> Level:
        """Parse a label such as ``"warning"``."""
        try:
            return cls[label.strip().upper()]
        except KeyError:
            raise ValueError(f"unknown level {label!r}") from None


def _check_unit_interval(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:  # also rejects NaN
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")


def _check_time(name: str, value: float) -> None:
    if not (math.isfinite(value) and value >= 0.0):
        raise ValueError(f"{name} must be a finite, non-negative number of seconds, got {value!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class Segment:
    """A closed stretch of speech from one stream, after ASR.

    Times are seconds since session start.
    """

    session_id: str
    seg_id: int
    stream: Stream
    t_start: float
    t_end: float
    text: str
    lang: str | None = None
    asr_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.seg_id < 0:
            raise ValueError(f"seg_id must be non-negative, got {self.seg_id}")
        _check_time("t_start", self.t_start)
        _check_time("t_end", self.t_end)
        if self.t_end < self.t_start:
            raise ValueError(f"t_end ({self.t_end}) is before t_start ({self.t_start})")
        _check_time("asr_ms", self.asr_ms)

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


@dataclass(frozen=True, slots=True, kw_only=True)
class Signal:
    """One piece of evidence.

    ``t`` is when the evidence was spoken (the start of its segment), never when a detector
    reported it. LLM latency therefore cannot reorder the attack chain.
    """

    t: float
    kind: SignalKind
    source: SignalSource
    tier: Tier
    speaker: Stream
    confidence: float
    evidence: str = ""
    seg_id: int | None = None

    def __post_init__(self) -> None:
        _check_time("t", self.t)
        _check_unit_interval("confidence", self.confidence)

    def with_confidence(self, confidence: float) -> Signal:
        """A copy with a different confidence (used by the bounded LLM discount)."""
        return replace(self, confidence=confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextEvent:
    """Something observed on the desktop: a process, a window title, a download, an OCR hit."""

    t: float
    kind: ContextKind
    detail: str = ""

    def __post_init__(self) -> None:
        _check_time("t", self.t)

    @property
    def objective(self) -> Objective | None:
        return self.kind.objective


@dataclass(frozen=True, slots=True, kw_only=True)
class ChainState:
    """Snapshot of one attack-chain template's progress.

    ``steps_seen`` holds ``(step_id, first_seen_time)`` pairs in the order the steps were
    first seen. A tuple keeps the snapshot hashable and gives the Why panel its timeline.
    """

    template: str
    objective: Objective
    progress: float
    order_score: float
    steps_seen: tuple[tuple[str, float], ...] = ()
    required_seen: bool = False
    distinctive_seen: bool = False

    def __post_init__(self) -> None:
        _check_unit_interval("progress", self.progress)
        _check_unit_interval("order_score", self.order_score)

    def first_seen(self, step_id: str) -> float | None:
        """When a step was first seen, or None. Linear scan: templates have at most a few steps."""
        for seen_id, t in self.steps_seen:
            if seen_id == step_id:
                return t
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskState:
    """The engine's output after each update: what the UI shows and what evaluation scores."""

    t: float
    score: float
    level: Level
    objective: Objective
    chain: ChainState | None = None
    coercion: bool = False
    llm_assessed: bool = False
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check_time("t", self.t)
        _check_unit_interval("score", self.score)

    @classmethod
    def quiet(cls, t: float = 0.0) -> RiskState:
        """The state at session start."""
        return cls(t=t, score=0.0, level=Level.QUIET, objective=Objective.NONE)
