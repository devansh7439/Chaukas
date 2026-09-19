from __future__ import annotations

import pytest

from chaukas.core.config import load_config
from chaukas.core.models import (
    ChainState,
    ContextEvent,
    ContextKind,
    Objective,
    Signal,
    SignalKind,
    SignalSource,
    Stream,
    Tier,
)
from chaukas.engine.chains import ChainTracker
from chaukas.engine.templates import load_templates

K = SignalKind
TEMPLATES = load_templates()
CHAIN_CONFIG = load_config().engine.chain


def caller(kind: SignalKind, t: float, confidence: float = 0.5) -> Signal:
    return Signal(
        t=t,
        kind=kind,
        source=SignalSource.KEYWORD,
        tier=Tier.STRONG,
        speaker=Stream.CALLER,
        confidence=confidence,
    )


def feed(tracker: ChainTracker, *kinds: SignalKind | ContextKind) -> None:
    for t, kind in enumerate(kinds, start=1):
        if isinstance(kind, ContextKind):
            tracker.observe_context(ContextEvent(t=float(t), kind=kind))
        else:
            tracker.observe_signal(caller(kind, float(t)))


def state(tracker: ChainTracker, name: str) -> ChainState:
    return next(s for s in tracker.states() if s.template == name)


@pytest.fixture
def tracker() -> ChainTracker:
    return ChainTracker(TEMPLATES, CHAIN_CONFIG)


def test_progress_is_seen_weight_over_total(tracker: ChainTracker) -> None:
    feed(tracker, K.AUTHORITY, K.THREAT)
    da = state(tracker, "digital_arrest")
    assert da.progress == pytest.approx(2.0 / 5.4)
    assert da.order_score == 1.0
    assert not da.required_seen
    assert not da.distinctive_seen
    assert da.steps_seen == (("authority", 1.0), ("threat", 2.0))


def test_missing_required_steps_cap_progress(tracker: ChainTracker) -> None:
    feed(tracker, K.AUTHORITY, K.THREAT, K.ISOLATION, ContextKind.BANK_PAGE)  # 4.2 / 5.4
    assert state(tracker, "digital_arrest").progress == CHAIN_CONFIG.required_step_cap


def test_complete_chain_in_order(tracker: ChainTracker) -> None:
    feed(tracker, K.AUTHORITY, K.THREAT, K.ISOLATION, K.MONEY_REQUEST, ContextKind.TRANSFER_PAGE)
    da = state(tracker, "digital_arrest")
    assert da.progress == 1.0
    assert da.required_seen
    assert da.distinctive_seen


def test_reversed_order_is_penalised(tracker: ChainTracker) -> None:
    feed(tracker, K.MONEY_REQUEST, K.ISOLATION, K.THREAT, K.AUTHORITY)
    da = state(tracker, "digital_arrest")
    assert da.order_score == 0.0
    assert da.progress == pytest.approx(4.4 / 5.4 * CHAIN_CONFIG.order_penalty)


def test_weak_and_user_signals_are_ignored(tracker: ChainTracker) -> None:
    assert not tracker.observe_signal(caller(K.AUTHORITY, 1.0, confidence=0.3))
    user = Signal(
        t=2.0,
        kind=K.AUTHORITY,
        source=SignalSource.KEYWORD,
        tier=Tier.STRONG,
        speaker=Stream.USER,
        confidence=0.5,
    )
    assert not tracker.observe_signal(user)
    assert tracker.active() is None


def test_observe_reports_only_new_steps(tracker: ChainTracker) -> None:
    assert tracker.observe_signal(caller(K.THREAT, 5.0))
    assert not tracker.observe_signal(caller(K.THREAT, 9.0))


def test_a_late_signal_quoting_earlier_speech_moves_first_seen_back(
    tracker: ChainTracker,
) -> None:
    tracker.observe_signal(caller(K.THREAT, 30.0))
    tracker.observe_signal(caller(K.THREAT, 12.0))
    assert state(tracker, "digital_arrest").first_seen("threat") == 12.0


def test_active_chain_tie_breaking(tracker: ChainTracker) -> None:
    feed(tracker, K.AUTHORITY, K.THREAT)
    # remote_access 0.43 and credential_theft 0.42 tie; digital_arrest 0.37 is outside the margin.
    assert tracker.active().template == "remote_access"  # type: ignore[union-attr]
    hinted = tracker.active(hint=Objective.CREDENTIAL_DISCLOSURE)
    assert hinted is not None
    assert hinted.template == "credential_theft"
    tracker.observe_signal(caller(K.ISOLATION, 3.0))
    assert tracker.active().template == "digital_arrest"  # type: ignore[union-attr]


def test_reset(tracker: ChainTracker) -> None:
    feed(tracker, K.AUTHORITY)
    tracker.reset()
    assert tracker.active() is None


def test_requires_templates() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ChainTracker((), CHAIN_CONFIG)
