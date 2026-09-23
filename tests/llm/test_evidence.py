"""The evidence guard: LLM items must quote the caller line they cite."""

from __future__ import annotations

import json
from typing import Any

import pytest

from chaukas.core.models import Objective, Segment, SignalKind, SignalSource, Stream, Tier
from chaukas.llm.evidence import GuardResult, apply_guard, token_overlap
from chaukas.llm.schema import parse_reply

K = SignalKind


def seg(seg_id: int, stream: Stream, t: float, text: str) -> Segment:
    return Segment(
        session_id="s", seg_id=seg_id, stream=stream, t_start=t, t_end=t + 2.0, text=text
    )


LINES = {
    1: seg(1, Stream.CALLER, 0.0, "Main CBI se bol raha hoon, Delhi cyber cell se."),
    2: seg(2, Stream.USER, 3.0, "Kya hua sir?"),
    3: seg(3, Stream.CALLER, 5.0, "Aapke naam pe arrest warrant hai, giraftar ho sakte hain."),
    4: seg(4, Stream.CALLER, 9.0, "Aapke phone par OTP aaya hai, OTP batao."),
    5: seg(5, Stream.USER, 13.0, "Saat aath nau paanch."),
}


def guard(**reply: Any) -> GuardResult:
    data: dict[str, Any] = {
        "addressed_to_user": True,
        "claimed_identity": "cbi",
        "tactics": [],
        "requested_actions": [],
        "user_compliance": "unclear",
        "suspected_objective": "unclear",
    }
    data.update(reply)
    return apply_guard(
        parse_reply(json.dumps(data)),
        LINES,
        t_available=20.0,
        min_overlap=0.6,
        compliance_confidence=0.9,
    )


def tactic(name: str, line: int, evidence: str, confidence: float = 0.8) -> dict[str, Any]:
    return {"name": name, "line": line, "evidence": evidence, "confidence": confidence}


def action(name: str, line: int, evidence: str, confidence: float = 0.8) -> dict[str, Any]:
    return {"action": name, "line": line, "evidence": evidence, "confidence": confidence}


def test_token_overlap_is_the_share_of_quote_tokens_found_in_the_line() -> None:
    assert token_overlap("arrest warrant", "Aapke naam pe arrest warrant hai") == 1.0
    assert token_overlap("arrest warrant jail", "arrest warrant hai") == pytest.approx(2 / 3)
    assert token_overlap("", "anything") == 0.0


def test_a_faithful_quote_becomes_a_signal_timed_at_its_line() -> None:
    result = guard(tactics=[tactic("threat", 3, "arrest warrant hai")])
    (signal,) = result.signals
    assert signal.kind is K.THREAT
    assert signal.t == 5.0
    assert signal.seg_id == 3
    assert signal.source is SignalSource.LLM
    assert signal.tier is Tier.LLM
    assert signal.speaker is Stream.CALLER
    assert signal.confidence == 0.8
    assert (result.accepted, result.rejected) == (1, 0)


@pytest.mark.parametrize(
    "item",
    [
        tactic("threat", 3, "you will be deported tomorrow"),  # hallucinated quote
        tactic("threat", 99, "arrest warrant hai"),  # line not in the window
        tactic("isolation", 2, "Kya hua sir"),  # quotes the USER
    ],
)
def test_unfaithful_items_are_rejected(item: dict[str, Any]) -> None:
    result = guard(tactics=[item])
    assert result.signals == ()
    assert (result.accepted, result.rejected) == (0, 1)


@pytest.mark.parametrize(
    ("name", "kind", "confidence"),
    [
        ("money_transfer", K.MONEY_REQUEST, 0.8),
        ("install_remote_app", K.REMOTE_ACCESS_REQUEST, 0.8),
        ("share_screen", K.REMOTE_ACCESS_REQUEST, 0.8),
        ("download_file", K.REMOTE_ACCESS_REQUEST, 0.8),
        ("disclose_otp", K.CREDENTIAL_REQUEST, 0.8),
        ("disclose_password", K.CREDENTIAL_REQUEST, 0.8),
        ("open_bank_site", K.MONEY_REQUEST, 0.4),  # half confidence
    ],
)
def test_requested_actions_map_to_request_signals(
    name: str, kind: SignalKind, confidence: float
) -> None:
    (signal,) = guard(requested_actions=[action(name, 4, "OTP batao")]).signals
    assert signal.kind is kind
    assert signal.confidence == pytest.approx(confidence)


def test_the_assessment_covers_caller_lines_and_lists_accepted_kinds() -> None:
    result = guard(
        addressed_to_user=False,
        suspected_objective="credential_disclosure",
        tactics=[tactic("authority", 1, "CBI se bol raha hoon"), tactic("threat", 3, "invented")],
    )
    assessment = result.assessment
    assert assessment.t == 20.0
    assert assessment.addressed_to_user is False
    assert assessment.suspected_objective is Objective.CREDENTIAL_DISCLOSURE
    assert assessment.covered_seg_ids == frozenset({1, 3, 4})
    assert assessment.listed_kinds == frozenset({K.AUTHORITY})


def test_compliance_after_a_credential_request_counts_as_disclosure() -> None:
    result = guard(
        user_compliance="complied",
        requested_actions=[action("disclose_otp", 4, "OTP batao")],
    )
    digits = [s for s in result.signals if s.kind is K.USER_DIGITS_SPOKEN]
    assert len(digits) == 1
    assert digits[0].speaker is Stream.USER
    assert digits[0].t == 13.0  # the first user line after the request
    assert digits[0].confidence == 0.9


def test_compliance_without_an_accepted_credential_request_is_ignored() -> None:
    result = guard(user_compliance="complied", tactics=[tactic("threat", 3, "arrest warrant")])
    assert all(s.kind is not K.USER_DIGITS_SPOKEN for s in result.signals)


def test_quotes_are_trimmed_for_the_why_panel() -> None:
    long_quote = "Aapke naam pe arrest warrant hai, giraftar ho sakte hain. " * 3
    (signal,) = guard(tactics=[tactic("threat", 3, long_quote)]).signals
    assert len(signal.evidence) <= 80
