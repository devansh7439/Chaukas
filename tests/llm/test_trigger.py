"""When the LLM is called (blueprint 6.4)."""

from __future__ import annotations

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
from chaukas.llm.trigger import TriggerPolicy

CONFIG = load_config().llm  # debounce 8 s, heartbeat 45 s, min speech 10 s


def signal(tier: Tier, t: float = 1.0, speaker: Stream = Stream.CALLER) -> Signal:
    return Signal(
        t=t, kind=SignalKind.THREAT, source=SignalSource.KEYWORD, tier=tier, speaker=speaker,
        confidence=0.5,
    )  # fmt: skip


def speech(t: float, duration: float, stream: Stream = Stream.CALLER) -> Segment:
    return Segment(
        session_id="s", seg_id=0, stream=stream, t_start=t, t_end=t + duration, text="..."
    )


def test_quiet_until_something_happens() -> None:
    assert not TriggerPolicy(CONFIG).due(100.0)


def test_strong_keywords_fire_at_once_but_weak_ones_never_do() -> None:
    policy = TriggerPolicy(CONFIG)
    policy.on_signal(signal(Tier.WEAK))
    assert not policy.due(2.0)
    policy.on_signal(signal(Tier.STRONG))
    assert policy.due(2.0)


def test_user_keywords_and_llm_signals_do_not_fire() -> None:
    policy = TriggerPolicy(CONFIG)
    policy.on_signal(signal(Tier.STRONG, speaker=Stream.USER))
    policy.on_signal(signal(Tier.LLM))
    assert not policy.due(2.0)


def test_debounce_and_single_flight() -> None:
    policy = TriggerPolicy(CONFIG)
    policy.on_signal(signal(Tier.PHRASE))
    policy.started(10.0)
    policy.on_signal(signal(Tier.FAST_PATH, t=11.0))
    assert not policy.due(30.0)  # still in flight
    policy.finished()
    assert not policy.due(17.9)  # within the 8 s debounce
    assert policy.due(18.0)


def test_context_fires_only_once_an_alert_is_showing() -> None:
    policy = TriggerPolicy(CONFIG)
    page = ContextEvent(t=5.0, kind=ContextKind.BANK_PAGE)
    policy.on_context(page, Level.QUIET)
    assert not policy.due(6.0)
    policy.on_context(page, Level.NOTICE)
    assert policy.due(6.0)


def test_window_changes_never_fire() -> None:
    policy = TriggerPolicy(CONFIG)
    policy.on_context(ContextEvent(t=5.0, kind=ContextKind.WINDOW_CHANGED), Level.WARNING)
    assert not policy.due(6.0)


def test_heartbeat_needs_enough_new_caller_speech() -> None:
    policy = TriggerPolicy(CONFIG)
    policy.on_segment(speech(0.0, 6.0))
    policy.on_segment(speech(7.0, 30.0, Stream.USER))  # user speech does not count
    assert not policy.due(50.0)
    policy.on_segment(speech(40.0, 5.0))
    assert not policy.due(44.9)
    assert policy.due(45.0)
    policy.started(45.0)
    policy.finished()
    policy.on_segment(speech(50.0, 12.0))
    assert not policy.due(89.9)
    assert policy.due(90.0)


def test_reset_forgets_pending_work() -> None:
    policy = TriggerPolicy(CONFIG)
    policy.on_signal(signal(Tier.STRONG))
    policy.started(1.0)
    policy.reset()
    assert not policy.due(100.0)
