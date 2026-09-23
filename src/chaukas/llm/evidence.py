"""Evidence guard (blueprint 6.4): LLM items become signals only if they quote real speech.

Each tactic or requested action must cite a CALLER line in the prompt window and quote it:
at least ``min_overlap`` of the quote's tokens must appear in that line. Anything else is
dropped as a hallucination. A kept item becomes a signal timed at its line's start, so LLM
latency can never reorder the attack chain.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from chaukas.core.models import (
    LLMAssessment,
    Segment,
    Signal,
    SignalKind,
    SignalSource,
    Stream,
    Tier,
)
from chaukas.llm.schema import LLMReply, RequestedAction, Tactic
from chaukas.signals.normalise import tokenize

MAX_EVIDENCE_CHARS: Final = 80

# action -> (signal kind, confidence factor)
_ACTIONS: Final[Mapping[str, tuple[SignalKind, float]]] = MappingProxyType(
    {
        "money_transfer": (SignalKind.MONEY_REQUEST, 1.0),
        "install_remote_app": (SignalKind.REMOTE_ACCESS_REQUEST, 1.0),
        "share_screen": (SignalKind.REMOTE_ACCESS_REQUEST, 1.0),
        "download_file": (SignalKind.REMOTE_ACCESS_REQUEST, 1.0),
        "disclose_otp": (SignalKind.CREDENTIAL_REQUEST, 1.0),
        "disclose_password": (SignalKind.CREDENTIAL_REQUEST, 1.0),
        "open_bank_site": (SignalKind.MONEY_REQUEST, 0.5),
    }
)


@dataclass(frozen=True, slots=True)
class GuardResult:
    signals: tuple[Signal, ...]
    assessment: LLMAssessment
    accepted: int
    rejected: int


def token_overlap(quote: str, line: str) -> float:
    """Share of the quote's tokens that also appear in the line (0 for an empty quote)."""
    quote_tokens = tokenize(quote)
    if not quote_tokens:
        return 0.0
    line_tokens = set(tokenize(line))
    return sum(token in line_tokens for token in quote_tokens) / len(quote_tokens)


def apply_guard(
    reply: LLMReply,
    lines: Mapping[int, Segment],
    *,
    t_available: float,
    min_overlap: float,
    compliance_confidence: float,
) -> GuardResult:
    """Turn a parsed reply into signals and an assessment. ``lines`` maps seg_id -> segment
    for every line the prompt showed."""
    signals: list[Signal] = []
    rejected = 0
    items: tuple[Tactic | RequestedAction, ...] = (*reply.tactics, *reply.requested_actions)
    for item in items:
        line = _cited_caller_line(item, lines, min_overlap)
        if line is None:
            rejected += 1
            continue
        kind, factor = _kind_of(item)
        signals.append(
            Signal(
                t=line.t_start,
                kind=kind,
                source=SignalSource.LLM,
                tier=Tier.LLM,
                speaker=Stream.CALLER,
                confidence=item.confidence * factor,
                evidence=_trim(item.evidence),
                seg_id=line.seg_id,
            )
        )
    accepted = len(signals)
    listed = frozenset(signal.kind for signal in signals)
    if reply.user_compliance == "complied":
        compliance = _compliance_signal(signals, lines, compliance_confidence)
        if compliance is not None:
            signals.append(compliance)
    assessment = LLMAssessment(
        t=t_available,
        addressed_to_user=reply.addressed_to_user,
        suspected_objective=reply.suspected_objective,
        covered_seg_ids=frozenset(
            seg_id for seg_id, line in lines.items() if line.stream is Stream.CALLER
        ),
        listed_kinds=listed,
    )
    return GuardResult(
        signals=tuple(signals), assessment=assessment, accepted=accepted, rejected=rejected
    )


def _cited_caller_line(
    item: Tactic | RequestedAction, lines: Mapping[int, Segment], min_overlap: float
) -> Segment | None:
    line = lines.get(item.line)
    if line is None or line.stream is not Stream.CALLER:
        return None
    if token_overlap(item.evidence, line.text) < min_overlap:
        return None
    return line


def _kind_of(item: Tactic | RequestedAction) -> tuple[SignalKind, float]:
    if isinstance(item, Tactic):
        return SignalKind(item.name), 1.0
    return _ACTIONS[item.action]


def _compliance_signal(
    signals: list[Signal], lines: Mapping[int, Segment], confidence: float
) -> Signal | None:
    """``complied`` after a caller credential request counts like the user reading digits."""
    requests = [s.t for s in signals if s.kind is SignalKind.CREDENTIAL_REQUEST]
    if not requests:
        return None
    first_request = min(requests)
    answers = sorted(
        (line for line in lines.values() if line.stream is Stream.USER),
        key=lambda line: line.t_start,
    )
    answer = next((line for line in answers if line.t_start >= first_request), None)
    if answer is None:
        return None
    return Signal(
        t=answer.t_start,
        kind=SignalKind.USER_DIGITS_SPOKEN,
        source=SignalSource.LLM,
        tier=Tier.LLM,
        speaker=Stream.USER,
        confidence=confidence,
        evidence="the user appears to have complied",
        seg_id=answer.seg_id,
    )


def _trim(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_EVIDENCE_CHARS:
        return text
    return text[: MAX_EVIDENCE_CHARS - 1].rstrip() + "…"
