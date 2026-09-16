from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

from chaukas.core.models import (
    ChainState,
    ContextEvent,
    ContextKind,
    Level,
    Objective,
    RiskState,
    Segment,
    Signal,
    SignalKind,
    SignalSource,
    Stream,
    Tier,
)


def make_signal(**overrides: Any) -> Signal:
    fields: dict[str, Any] = {
        "t": 1.0,
        "kind": SignalKind.THREAT,
        "source": SignalSource.KEYWORD,
        "tier": Tier.STRONG,
        "speaker": Stream.CALLER,
        "confidence": 0.5,
    }
    fields.update(overrides)
    return Signal(**fields)


def make_segment(**overrides: Any) -> Segment:
    fields: dict[str, Any] = {
        "session_id": "s1",
        "seg_id": 0,
        "stream": Stream.CALLER,
        "t_start": 1.0,
        "t_end": 3.5,
        "text": "CBI se bol raha hoon",
    }
    fields.update(overrides)
    return Segment(**fields)


class TestLevel:
    def test_levels_escalate_in_declaration_order(self) -> None:
        assert list(Level) == sorted(Level)
        assert Level.QUIET < Level.NOTICE < Level.WARNING < Level.CRITICAL
        assert Level.CRITICAL < Level.CRITICAL_RECOVERY
        assert max(Level.NOTICE, Level.CRITICAL, Level.WARNING) is Level.CRITICAL

    def test_parse_round_trips_every_label(self) -> None:
        for level in Level:
            assert Level.parse(level.label) is level

    def test_parse_ignores_case_and_whitespace(self) -> None:
        assert Level.parse(" Warning ") is Level.WARNING

    def test_parse_rejects_unknown_label(self) -> None:
        with pytest.raises(ValueError, match="unknown level"):
            Level.parse("panic")


class TestKinds:
    def test_only_threat_isolation_and_surveillance_are_coercive(self) -> None:
        coercive = {kind for kind in SignalKind if kind.is_coercive}
        assert coercive == {SignalKind.THREAT, SignalKind.ISOLATION, SignalKind.SURVEILLANCE}

    def test_request_kinds(self) -> None:
        requests = {kind for kind in SignalKind if kind.is_request}
        assert requests == {
            SignalKind.MONEY_REQUEST,
            SignalKind.REMOTE_ACCESS_REQUEST,
            SignalKind.CREDENTIAL_REQUEST,
        }

    @pytest.mark.parametrize(
        ("kind", "objective"),
        [
            (ContextKind.REMOTE_APP_STARTED, Objective.REMOTE_CONTROL),
            (ContextKind.DOWNLOAD_EXECUTABLE, Objective.REMOTE_CONTROL),
            (ContextKind.BANK_PAGE, Objective.MONEY_TRANSFER),
            (ContextKind.TRANSFER_PAGE, Objective.MONEY_TRANSFER),
            (ContextKind.OTP_FIELD_VISIBLE, Objective.CREDENTIAL_DISCLOSURE),
            (ContextKind.PASSWORD_FIELD_VISIBLE, Objective.CREDENTIAL_DISCLOSURE),
            (ContextKind.WINDOW_CHANGED, None),
        ],
    )
    def test_context_objective(self, kind: ContextKind, objective: Objective | None) -> None:
        assert kind.objective is objective
        assert ContextEvent(t=0.0, kind=kind).objective is objective


class TestSignal:
    def test_is_immutable_and_slotted(self) -> None:
        signal = make_signal()
        with pytest.raises(dataclasses.FrozenInstanceError):
            signal.confidence = 0.9  # type: ignore[misc]
        assert not hasattr(signal, "__dict__")

    @pytest.mark.parametrize("confidence", [-0.01, 1.01, math.nan])
    def test_rejects_confidence_outside_unit_interval(self, confidence: float) -> None:
        with pytest.raises(ValueError, match="confidence"):
            make_signal(confidence=confidence)

    @pytest.mark.parametrize("t", [-1.0, math.inf, math.nan])
    def test_rejects_invalid_time(self, t: float) -> None:
        with pytest.raises(ValueError, match="t must be"):
            make_signal(t=t)

    def test_with_confidence_returns_a_validated_copy(self) -> None:
        original = make_signal(confidence=0.5)
        discounted = original.with_confidence(0.25)
        assert discounted.confidence == 0.25
        assert original.confidence == 0.5
        with pytest.raises(ValueError, match="confidence"):
            original.with_confidence(2.0)


class TestSegment:
    def test_duration(self) -> None:
        assert make_segment(t_start=1.0, t_end=3.5).duration == 2.5

    def test_rejects_end_before_start(self) -> None:
        with pytest.raises(ValueError, match="before t_start"):
            make_segment(t_start=5.0, t_end=4.0)

    def test_rejects_negative_seg_id(self) -> None:
        with pytest.raises(ValueError, match="seg_id"):
            make_segment(seg_id=-1)


class TestChainState:
    def test_first_seen_and_hashability(self) -> None:
        state = ChainState(
            template="digital_arrest",
            objective=Objective.MONEY_TRANSFER,
            progress=0.37,
            order_score=1.0,
            steps_seen=(("authority", 12.0), ("threat", 31.0)),
        )
        assert state.first_seen("threat") == 31.0
        assert state.first_seen("money") is None
        assert hash(state) == hash(dataclasses.replace(state))

    def test_rejects_progress_outside_unit_interval(self) -> None:
        with pytest.raises(ValueError, match="progress"):
            ChainState(template="x", objective=Objective.UNCLEAR, progress=1.2, order_score=1.0)


def test_risk_state_quiet() -> None:
    state = RiskState.quiet(t=4.0)
    assert state.level is Level.QUIET
    assert state.objective is Objective.NONE
    assert state.score == 0.0
    assert state.reasons == ()
