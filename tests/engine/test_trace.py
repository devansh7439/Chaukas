"""The decision trace: every alert carries the numbers that produced it, and the Why panel
is built from them. Nothing here is persisted: the trace lives in the RiskState only."""

from __future__ import annotations

import pytest

from chaukas.core.config import load_config
from chaukas.core.models import (
    ContextEvent,
    ContextKind,
    Level,
    Segment,
    Signal,
    SignalKind,
    SignalSource,
    Stream,
    Tier,
)
from chaukas.engine.risk import RiskEngine
from chaukas.engine.templates import load_templates

K = SignalKind
WEIGHTS = load_config().engine.weights


def make_engine() -> RiskEngine:
    return RiskEngine.from_config(load_config({"ablation": {"use_llm": False}}), load_templates())


def signal(
    kind: SignalKind,
    confidence: float,
    t: float,
    source: SignalSource = SignalSource.KEYWORD,
    words: str = "",
) -> Signal:
    tier = Tier.SEMANTIC if source is SignalSource.SEMANTIC else Tier.FAST_PATH
    return Signal(t=t, kind=kind, source=source, tier=tier, speaker=Stream.CALLER,
                  confidence=confidence, evidence=words or kind.value, seg_id=int(t))  # fmt: skip


def talk(engine: RiskEngine, start: float, seconds: float) -> float:
    engine.on_segment(Segment(session_id="s", seg_id=999, stream=Stream.CALLER,
                              t_start=start, t_end=start + seconds, text=""))  # fmt: skip
    return start + seconds


class TestEntries:
    def test_each_reason_carries_source_confidence_and_contribution(self) -> None:
        engine = make_engine()
        engine.on_signal(signal(K.AUTHORITY, 0.6, 0.0, words="cbi se"))
        engine.on_signal(signal(K.CREDENTIAL_REQUEST, 0.72, 2.0, SignalSource.SEMANTIC,
                                'sounds like "read me the digits"'))  # fmt: skip
        state = engine.evaluate(3.0)
        assert state.level is Level.CRITICAL
        authority, request = state.reasons
        assert (request.label, request.source, request.confidence) == (
            "credential_request", "semantic", 0.72)  # fmt: skip
        assert request.current == pytest.approx(0.72)  # no speech yet, so no decay
        assert request.contribution == pytest.approx(WEIGHTS[K.CREDENTIAL_REQUEST] * 0.72)
        assert request.chain_step == "cred_req"
        assert authority.source == "keyword"
        assert authority.chain_step == "authority"

    def test_decay_shows_in_current_but_not_in_confidence(self) -> None:
        engine = make_engine()
        engine.on_signal(signal(K.THREAT, 0.5, 0.0))
        now = talk(engine, 0.0, 600.0)  # one half-life of speech
        (threat,) = engine.evaluate(now).reasons
        assert threat.confidence == 0.5
        assert threat.current == pytest.approx(0.25, rel=0.01)

    def test_context_events_are_entries_too(self) -> None:
        engine = make_engine()
        engine.on_context(ContextEvent(t=5.0, kind=ContextKind.BANK_PAGE, detail="MyBank"))
        (entry,) = engine.evaluate(6.0).reasons
        assert (entry.label, entry.source, entry.detail) == ("bank_page", "screen", "MyBank")


class TestRule:
    def test_names_the_rule_that_set_the_level(self) -> None:
        engine = make_engine()
        engine.on_signal(signal(K.CREDENTIAL_REQUEST, 0.75, 0.0))
        state = engine.evaluate(1.0)
        assert (state.level, state.rule) == (Level.WARNING, "pre_disclosure")
        engine.on_signal(signal(K.AUTHORITY, 0.6, 2.0))
        state = engine.evaluate(3.0)
        assert (state.level, state.rule) == (Level.CRITICAL, "pre_disclosure_primed")

    def test_plain_scoring_is_the_threshold_rule(self) -> None:
        engine = make_engine()
        engine.on_signal(signal(K.URGENCY, 0.5, 0.0))
        assert engine.evaluate(1.0).rule == "threshold"


class TestRelevance:
    def test_stale_evidence_is_not_offered_as_a_reason(self) -> None:
        # Loopback heard "CBI" in a video an hour of speech ago; today's OTP warning must
        # not quote it.
        engine = make_engine()
        engine.on_signal(signal(K.AUTHORITY, 0.6, 0.0, words="cbi"))
        now = talk(engine, 1.0, 3600.0)
        engine.on_signal(signal(K.CREDENTIAL_REQUEST, 0.75, now))
        state = engine.evaluate(now + 1.0)
        assert state.level is Level.WARNING
        assert [reason.label for reason in state.reasons] == ["credential_request"]

    def test_a_held_alert_keeps_the_reasons_that_raised_it(self) -> None:
        engine = make_engine()
        engine.on_signal(signal(K.AUTHORITY, 0.6, 0.0, words="cbi"))
        engine.on_signal(signal(K.CREDENTIAL_REQUEST, 0.75, 1.0, words="otp batao"))
        assert engine.evaluate(2.0).level is Level.CRITICAL
        now = talk(engine, 2.0, 3600.0)  # the caller stalls for an hour
        state = engine.evaluate(now)
        assert (state.level, state.rule) == (Level.CRITICAL, "held")
        assert [(r.label, r.detail) for r in state.reasons] == [
            ("authority", "cbi"), ("credential_request", "otp batao")]  # fmt: skip
