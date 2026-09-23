from __future__ import annotations

import pytest

from chaukas.core.config import load_config
from chaukas.core.models import (
    ContextEvent,
    ContextKind,
    Level,
    LLMAssessment,
    Objective,
    Segment,
    SignalKind,
    Stream,
)
from chaukas.engine.risk import RiskEngine
from chaukas.evaluation.ablation import config_for
from chaukas.evaluation.session import Session
from chaukas.signals.extractor import SignalExtractor
from chaukas.signals.lexicon import Lexicon


def make_session(lexicon: Lexicon, *, ablation: str = "E", tick_s: float = 1.0) -> Session:
    config = config_for(ablation)
    return Session(
        SignalExtractor(lexicon, config.signals),
        RiskEngine.from_config(config),
        tick_s=tick_s,
        session_id="test",
    )


def caller_segment(session: Session, text: str, t: float, duration: float = 2.0) -> Segment:
    return Segment(
        session_id=session.session_id,
        seg_id=session.next_segment_id(),
        stream=Stream.CALLER,
        t_start=t,
        t_end=t + duration,
        text=text,
    )


def test_ticks_evaluate_while_nothing_happens(lexicon: Lexicon) -> None:
    session = make_session(lexicon)
    snapshots = session.advance_to(5.0)
    assert [snapshot.t for snapshot in snapshots] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert all(snapshot.level is Level.QUIET for snapshot in snapshots)
    assert not any(snapshot.changed for snapshot in snapshots)
    assert session.now == 5.0


def test_going_backwards_is_a_no_op(lexicon: Lexicon) -> None:
    session = make_session(lexicon)
    session.advance_to(10.0)
    assert session.advance_to(5.0) == []
    assert session.now == 10.0


def test_a_segment_produces_signals_and_flags_the_level_change(lexicon: Lexicon) -> None:
    session = make_session(lexicon)
    snapshots = session.feed_segment(
        caller_segment(session, "CBI se bol raha hoon, arrest warrant hai", t=0.0)
    )
    last = snapshots[-1]
    assert last.level is Level.NOTICE
    assert last.changed
    # A quiet tick afterwards is not a change.
    assert not session.advance_to(session.now + 1.0)[0].changed


def test_context_events_reach_the_engine(lexicon: Lexicon) -> None:
    session = make_session(lexicon)
    session.feed_segment(caller_segment(session, "CBI se bol raha hoon, giraftar ho jayenge", 0.0))
    session.feed_segment(caller_segment(session, "kisi ko mat batana, amount transfer karo", 4.0))
    before = session.advance_to(session.now + 1.0)[-1]
    after = session.feed_context(
        ContextEvent(t=session.now + 1.0, kind=ContextKind.TRANSFER_PAGE, detail="DemoBank (MOCK)")
    )[-1]
    assert after.state.score > before.state.score
    assert after.level is Level.CRITICAL


def test_dismissal_and_reset(lexicon: Lexicon) -> None:
    session = make_session(lexicon)
    session.feed_segment(caller_segment(session, "CBI se bol raha, arrest warrant hai", 0.0))
    assert session.dismiss()[-1].state.dismissed
    session.reset()
    state = session.advance_to(session.now + 1.0)[-1].state
    assert state.level is Level.QUIET
    assert state.reasons == ()


def test_reset_clears_the_extractor_state(lexicon: Lexicon) -> None:
    session = make_session(lexicon)
    session.feed_segment(caller_segment(session, "OTP batao", t=0.0))
    session.reset()
    user = Segment(
        session_id="test",
        seg_id=session.next_segment_id(),
        stream=Stream.USER,
        t_start=5.0,
        t_end=6.0,
        text="4567",
    )
    assert session.feed_segment(user)[-1].level is Level.QUIET


def test_tick_must_be_positive(lexicon: Lexicon) -> None:
    config = load_config()
    with pytest.raises(ValueError, match="tick_s"):
        Session(
            SignalExtractor(lexicon, config.signals),
            RiskEngine.from_config(config),
            tick_s=0.0,
        )


def test_llm_results_reach_the_engine(lexicon: Lexicon) -> None:
    session = make_session(lexicon, ablation="D")
    session.feed_segment(caller_segment(session, "CBI se bol raha hoon, arrest warrant hai", 0.0))
    assert session.state.level is Level.QUIET  # capped until the first LLM answer
    assert {s.kind for s in session.last_signals} == {SignalKind.AUTHORITY, SignalKind.THREAT}
    assessment = LLMAssessment(t=5.0, addressed_to_user=True, suspected_objective=Objective.NONE)
    snapshots = session.feed_llm(5.0, (), assessment)
    assert snapshots[-1].t == 5.0
    assert snapshots[-1].level is Level.NOTICE
    assert session.state.llm_assessed


def test_evaluate_at_an_exact_time(lexicon: Lexicon) -> None:
    session = make_session(lexicon)
    session.advance_to(2.5)  # ticks at 1.0 and 2.0 only
    assert session.now == 2.0
    snapshot = session.evaluate(2.5)
    assert snapshot.t == 2.5
    assert session.evaluate(1.0).t == 2.5  # never backwards
