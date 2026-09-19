from __future__ import annotations

import pytest

from chaukas.core.models import Signal, SignalKind, SignalSource, Stream, Tier
from chaukas.engine.activity import ActivityClock
from chaukas.engine.evidence import EvidenceStore

K = SignalKind


def signal(
    kind: SignalKind,
    confidence: float,
    t: float = 0.0,
    source: SignalSource = SignalSource.KEYWORD,
    seg_id: int = 1,
) -> Signal:
    tier = Tier.STRONG if source is SignalSource.KEYWORD else Tier.LLM
    return Signal(
        t=t,
        kind=kind,
        source=source,
        tier=tier,
        speaker=Stream.CALLER,
        confidence=confidence,
        seg_id=seg_id,
    )


def test_level_is_the_strongest_signal() -> None:
    store = EvidenceStore(600.0, ActivityClock())
    store.add(signal(K.THREAT, 0.5, t=1.0))
    store.add(signal(K.THREAT, 0.7, t=2.0))
    assert store.level(K.THREAT, now=1000.0) == 0.7  # no speech yet, so no decay
    assert store.level(K.AUTHORITY, now=1000.0) == 0.0
    assert store.strongest(K.AUTHORITY, now=1000.0) is None


def test_decay_follows_call_time_not_session_time() -> None:
    clock = ActivityClock()
    store = EvidenceStore(600.0, clock)
    clock.add(0.0, 10.0)
    store.add(signal(K.THREAT, 0.8, t=0.0))
    assert store.level(K.THREAT, now=5000.0) == pytest.approx(0.8 * 0.5 ** (10 / 600))
    clock.add(5000.0, 5600.0)
    assert store.level(K.THREAT, now=5600.0) == pytest.approx(0.8 * 0.5 ** (610 / 600))


def test_strongest_accounts_for_decay() -> None:
    clock = ActivityClock()
    store = EvidenceStore(600.0, clock)
    clock.add(0.0, 1200.0)
    old = signal(K.THREAT, 0.9, t=0.0)
    new = signal(K.THREAT, 0.6, t=1200.0)
    store.add(old)
    store.add(new)
    assert store.strongest(K.THREAT, now=1200.0) is new  # 0.9 decayed twice is 0.225


def test_discount_touches_only_matching_keyword_entries() -> None:
    store = EvidenceStore(600.0, ActivityClock())
    store.add(signal(K.AUTHORITY, 0.5, seg_id=1))
    store.add(signal(K.AUTHORITY, 0.8, seg_id=1, source=SignalSource.LLM))
    store.add(signal(K.THREAT, 0.5, seg_id=2))
    assert store.discount([K.AUTHORITY], {1}, 0.5) == 1
    assert store.level(K.AUTHORITY, now=0.0) == 0.8  # the LLM signal is untouched
    assert store.level(K.THREAT, now=0.0) == 0.5
    with pytest.raises(ValueError, match="factor"):
        store.discount([K.THREAT], {2}, 1.5)


def test_discount_lowers_the_peak_while_entries_are_live() -> None:
    store = EvidenceStore(600.0, ActivityClock())
    store.add(signal(K.AUTHORITY, 0.5, seg_id=1))
    store.discount([K.AUTHORITY], {1}, 0.5)
    assert store.peak(K.AUTHORITY) == 0.25


def test_prune_drops_faded_entries_but_keeps_the_session_peak() -> None:
    clock = ActivityClock()
    store = EvidenceStore(600.0, clock)
    store.add(signal(K.THREAT, 0.6, t=0.0))
    clock.add(0.0, 6000.0)  # ten half-lives
    store.prune(now=6000.0)
    assert store.level(K.THREAT, now=6000.0) == 0.0
    assert store.peak(K.THREAT) == 0.6


def test_reset_and_validation() -> None:
    store = EvidenceStore(600.0, ActivityClock())
    store.add(signal(K.THREAT, 0.6))
    store.reset()
    assert store.peak(K.THREAT) == 0.0
    with pytest.raises(ValueError, match="half_life_s"):
        EvidenceStore(0.0, ActivityClock())
