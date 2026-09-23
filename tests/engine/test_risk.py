"""The risk engine against the blueprint's worked examples (section 6.7) and special rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from chaukas.core.config import load_config
from chaukas.core.models import (
    ContextEvent,
    ContextKind,
    Level,
    LLMAssessment,
    Objective,
    RiskState,
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
C = ContextKind
TEMPLATES = load_templates()
TIER_BY_CONFIDENCE = {0.3: Tier.WEAK, 0.5: Tier.STRONG, 0.6: Tier.PHRASE, 0.75: Tier.FAST_PATH}


def make_engine(**ablation: bool) -> RiskEngine:
    overrides: dict[str, Any] = {"ablation": ablation} if ablation else {}
    return RiskEngine.from_config(load_config(overrides), TEMPLATES)


def caller(kind: SignalKind, confidence: float, t: float) -> Signal:
    return Signal(
        t=t,
        kind=kind,
        source=SignalSource.KEYWORD,
        tier=TIER_BY_CONFIDENCE[confidence],
        speaker=Stream.CALLER,
        confidence=confidence,
        evidence=kind.value,
        seg_id=int(t),
    )


def user_digits(t: float) -> Signal:
    return Signal(
        t=t,
        kind=K.USER_DIGITS_SPOKEN,
        source=SignalSource.RULE,
        tier=Tier.RULE,
        speaker=Stream.USER,
        confidence=0.9,
    )


def assessment(t: float, addressed: bool, **kwargs: Any) -> LLMAssessment:
    return LLMAssessment(
        t=t, addressed_to_user=addressed, suspected_objective=Objective.NONE, **kwargs
    )


@dataclass(frozen=True)
class Case:
    name: str
    signals: tuple[tuple[SignalKind, float], ...]
    context: tuple[ContextKind, ...]
    addressed: bool | None  # None: no LLM assessment has arrived yet
    p: float
    g: float
    a: float
    s: float
    r: float
    level: Level
    objective: Objective


def play(engine: RiskEngine, case: Case) -> float:
    """Feed a case; return the time just after its last event."""
    if case.addressed is not None:
        engine.on_assessment(assessment(0.0, case.addressed))
    t = 1.0
    for kind, confidence in case.signals:
        engine.on_signal(caller(kind, confidence, t))
        t += 1.0
    for context in case.context:
        engine.on_context(ContextEvent(t=t, kind=context, detail=context.value))
        t += 1.0
    return t


DIGITAL_ARREST_START = ((K.AUTHORITY, 0.5), (K.THREAT, 0.5))
WITH_ISOLATION = (*DIGITAL_ARREST_START, (K.ISOLATION, 0.6))
WITH_MONEY = (*WITH_ISOLATION, (K.MONEY_REQUEST, 0.75))
NEWS = (*DIGITAL_ARREST_START, (K.SURVEILLANCE, 0.6))
FAKE_SUPPORT = ((K.AUTHORITY, 0.6), (K.THREAT, 0.5), (K.REMOTE_ACCESS_REQUEST, 0.75))

M, R, CR = Objective.MONEY_TRANSFER, Objective.REMOTE_CONTROL, Objective.CREDENTIAL_DISCLOSURE
L = Level

CASES = [
    Case("1 news, before LLM", NEWS, (), None, 0.78, 1.0, 0.70, 0.84, 0.45, L.QUIET, M),
    Case("2 news, not addressed", NEWS, (), False, 0.78, 0.3, 0.70, 0.84, 0.14, L.QUIET, M),
    Case(
        "3 CBI + arrest warrant",
        DIGITAL_ARREST_START, (), True, 0.51, 1.0, 0.70, 0.77, 0.28, L.NOTICE, Objective.UNCLEAR,
    ),
    Case("4 + isolation", WITH_ISOLATION, (), True, 0.78, 1.0, 0.70, 0.84, 0.45, L.WARNING, M),
    Case(
        "5 + money + transfer page",
        WITH_MONEY, (C.TRANSFER_PAGE,), True, 0.91, 1.0, 1.00, 1.00, 0.91, L.CRITICAL, M,
    ),
    Case("6 paid from phone", WITH_MONEY, (), True, 0.91, 1.0, 0.70, 0.93, 0.59, L.WARNING, M),
    Case("7 fake support", FAKE_SUPPORT, (), True, 0.75, 1.0, 0.70, 0.89, 0.46, L.WARNING, R),
    Case(
        "8 + download",
        FAKE_SUPPORT, (C.DOWNLOAD_EXECUTABLE,), True, 0.75, 1.0, 1.00, 1.00, 0.75, L.CRITICAL, R,
    ),
    Case(
        "9 legit IT support",
        ((K.AUTHORITY, 0.3), (K.REMOTE_ACCESS_REQUEST, 0.75)), (C.REMOTE_APP_STARTED,),
        True, 0.53, 1.0, 1.00, 0.83, 0.44, L.NOTICE, R,
    ),
    Case(
        "10 legit IT support mentioning a virus",
        ((K.AUTHORITY, 0.3), (K.THREAT, 0.5), (K.REMOTE_ACCESS_REQUEST, 0.75)),
        (C.REMOTE_APP_STARTED,), True, 0.70, 1.0, 1.00, 0.90, 0.63, L.WARNING, R,
    ),
    Case(
        "11 family money call",
        ((K.MONEY_REQUEST, 0.75), (K.URGENCY, 0.3)), (C.BANK_PAGE,),
        True, 0.65, 1.0, 1.00, 0.76, 0.49, L.NOTICE, M,
    ),
    Case(
        "12 real bank, OTP advice suppressed",
        ((K.AUTHORITY, 0.3),), (), True, 0.15, 1.0, 0.70, 0.60, 0.06, L.QUIET, Objective.NONE,
    ),
    Case(
        "13 friend who is a police officer",
        DIGITAL_ARREST_START, (), True, 0.51, 1.0, 0.70, 0.77, 0.28, L.NOTICE, Objective.UNCLEAR,
    ),
    Case(
        "14 bank se bol raha, OTP batao",
        ((K.AUTHORITY, 0.6), (K.CREDENTIAL_REQUEST, 0.75)), (),
        True, 0.77, 1.0, 0.70, 0.85, 0.46, L.CRITICAL, CR,
    ),
    Case(
        "15 parent asks for OTP",
        ((K.CREDENTIAL_REQUEST, 0.75),), (), True, 0.68, 1.0, 0.70, 0.75, 0.35, L.WARNING, CR,
    ),
    Case(
        "16 work meeting",
        ((K.THREAT, 0.5), (K.CREDENTIAL_REQUEST, 0.5)), (),
        True, 0.64, 1.0, 0.70, 0.81, 0.36, L.NOTICE, CR,
    ),
]  # fmt: skip


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_worked_example(case: Case) -> None:
    engine = make_engine()
    state = engine.evaluate(play(engine, case))
    components = state.components
    assert components is not None
    close = {"abs": 0.006}
    assert components.pressure == pytest.approx(case.p, **close)
    assert components.addressed == pytest.approx(case.g, **close)
    assert components.action == pytest.approx(case.a, **close)
    assert components.sequence == pytest.approx(case.s, **close)
    assert state.score == pytest.approx(case.r, **close)
    assert state.level is case.level
    assert state.objective is case.objective


def talk_and_tick(engine: RiskEngine, start: float, seconds: float) -> RiskState:
    """The caller keeps talking for ``seconds``; evaluate every second, like a live session."""
    engine.on_segment(Segment(session_id="s", seg_id=99, stream=Stream.CALLER,
                              t_start=start, t_end=start + seconds, text=""))  # fmt: skip
    state = engine.evaluate(start)
    for step in range(1, int(seconds) + 1):
        state = engine.evaluate(start + step)
    return state


def case(name_prefix: str) -> Case:
    return next(c for c in CASES if c.name.startswith(name_prefix))


def evaluate_case(engine: RiskEngine, prefix: str, addressed: bool | None = None) -> RiskState:
    chosen = case(prefix)
    if addressed is not None or chosen.addressed is None:
        chosen = Case(**{**chosen.__dict__, "addressed": addressed})
    return engine.evaluate(play(engine, chosen))


class TestPreLLMCap:
    def test_lifts_after_the_failure_grace(self) -> None:
        engine = make_engine()
        end = play(engine, Case(**{**case("4 ").__dict__, "addressed": None}))
        assert engine.evaluate(end).level is L.QUIET
        grace = load_config().llm.failure_grace_s
        assert engine.evaluate(1.0 + grace).level is L.WARNING  # first trigger was at t=1

    def test_not_applied_without_the_llm(self) -> None:
        engine = make_engine(use_llm=False)
        state = engine.evaluate(play(engine, Case(**{**case("4 ").__dict__, "addressed": None})))
        assert state.level is L.WARNING


class TestAddressedGate:
    def test_llm_disabled_ignores_assessments(self) -> None:
        engine = make_engine(use_llm=False)
        state = engine.evaluate(play(engine, case("2 ")))
        assert state.components is not None
        assert state.components.addressed == 1.0

    def test_a_recent_true_outweighs_a_single_false(self) -> None:
        engine = make_engine()
        engine.on_assessment(assessment(0.0, True))
        engine.on_assessment(assessment(0.5, False))
        state = engine.evaluate(play(engine, Case(**{**case("3 ").__dict__, "addressed": None})))
        assert state.components is not None
        assert state.components.addressed == 1.0


class TestAblationFlags:
    def test_without_the_action_gate_context_is_not_needed_for_critical(self) -> None:
        engine = make_engine(use_action_gate=False)
        state = engine.evaluate(play(engine, case("6 ")))
        assert state.components is not None
        assert state.components.action == 1.0
        assert state.level is L.CRITICAL

    def test_without_the_sequence_gate(self) -> None:
        engine = make_engine(use_sequence=False)
        state = engine.evaluate(play(engine, case("3 ")))
        assert state.components is not None
        assert state.components.sequence == 1.0
        assert state.score == pytest.approx(0.51 * 0.70, abs=0.006)


class TestCredentialRules:
    def test_recovery_after_a_pre_disclosure_alert(self) -> None:
        engine = make_engine()
        end = play(engine, case("14 "))
        assert engine.evaluate(end).level is L.CRITICAL
        engine.on_signal(user_digits(end))
        state = engine.evaluate(end + 1.0)
        assert state.level is L.CRITICAL_RECOVERY
        assert state.objective is CR

    def test_digits_without_a_pre_disclosure_alert_are_a_warning(self) -> None:
        engine = make_engine()
        engine.on_assessment(assessment(0.0, True))
        engine.on_signal(user_digits(1.0))
        assert engine.evaluate(2.0).level is L.WARNING

    def test_pre_disclosure_critical_holds_while_the_caller_keeps_talking(self) -> None:
        # A fast-path request (0.75) decays below 0.7 after ~60 s of speech. The protection
        # must not lapse while the caller stalls: only the session boundary ends it.
        engine = make_engine()
        end = play(engine, case("14 "))
        assert engine.evaluate(end).level is L.CRITICAL
        state = talk_and_tick(engine, end, 600.0)
        assert state.level is L.CRITICAL
        assert state.objective is CR

    def test_recovery_holds_after_the_digits_fade(self) -> None:
        engine = make_engine()
        end = play(engine, case("14 "))
        engine.on_signal(user_digits(end))
        assert engine.evaluate(end + 1.0).level is L.CRITICAL_RECOVERY
        assert talk_and_tick(engine, end + 1.0, 1800.0).level is L.CRITICAL_RECOVERY

    def test_a_pre_disclosure_warning_is_not_held(self) -> None:
        # Without authority or coercion ("beta, OTP bata do") the warning fades normally.
        engine = make_engine()
        end = play(engine, case("15 "))
        assert engine.evaluate(end).level is L.WARNING
        assert talk_and_tick(engine, end, 1800.0).level is L.QUIET

    def test_a_later_attack_that_reaches_critical_shows_its_own_objective(self) -> None:
        engine = make_engine()
        end = talk_and_tick(engine, play(engine, case("14 ")), 600.0).t
        for offset, (kind, confidence) in enumerate(WITH_MONEY[1:], start=1):
            engine.on_signal(caller(kind, confidence, end + offset))
        engine.on_context(ContextEvent(t=end + 5.0, kind=C.TRANSFER_PAGE))
        state = engine.evaluate(end + 6.0)
        assert state.level is L.CRITICAL
        assert state.objective is M

    def test_reset_releases_the_hold(self) -> None:
        engine = make_engine()
        engine.evaluate(play(engine, case("14 ")))
        engine.reset()
        assert engine.evaluate(100.0).level is L.QUIET

    def test_not_addressed_downgrades_an_otp_request_but_never_silences_it(self) -> None:
        # The caller can try to talk the LLM into "not addressed to the user" (prompt
        # injection: "this is a recorded announcement"). That verdict may lower the OTP
        # alert to a warning, which still says never to share an OTP; it cannot remove it.
        engine = make_engine()
        state = engine.evaluate(play(engine, Case(**{**case("14 ").__dict__, "addressed": False})))
        assert state.level is L.WARNING
        assert state.objective is CR

    def test_not_addressed_cannot_undo_a_critical_already_raised(self) -> None:
        engine = make_engine()
        end = play(engine, case("14 "))
        assert engine.evaluate(end).level is L.CRITICAL
        engine.on_assessment(assessment(end + 1.0, False))  # a later, injected verdict
        assert talk_and_tick(engine, end + 1.0, 120.0).level is L.CRITICAL

    def test_user_keywords_are_not_evidence(self) -> None:
        engine = make_engine()
        engine.on_assessment(assessment(0.0, True))
        engine.on_signal(
            Signal(
                t=1.0,
                kind=K.AUTHORITY,
                source=SignalSource.KEYWORD,
                tier=Tier.STRONG,
                speaker=Stream.USER,
                confidence=0.5,
            )
        )
        assert engine.evaluate(2.0).score == 0.0


class TestLLMDiscount:
    def test_is_bounded_to_unconfirmed_generic_tactics_and_applied_once(self) -> None:
        engine = make_engine()
        engine.on_assessment(assessment(0.0, True))
        engine.on_signal(caller(K.AUTHORITY, 0.5, 1.0))
        engine.on_signal(caller(K.ISOLATION, 0.6, 1.0))
        covering = assessment(2.0, True, covered_seg_ids=frozenset({1}))
        engine.on_assessment(covering)
        expected = 1.0 - (1.0 - 0.5 * 0.25) * (1.0 - 0.9 * 0.6)  # authority halved only
        first = engine.evaluate(3.0).components
        engine.on_assessment(covering)  # a second reply covering the same segment
        second = engine.evaluate(4.0).components
        assert first is not None
        assert second is not None
        assert first.pressure == pytest.approx(expected)
        assert second.pressure == pytest.approx(expected)

    def test_listed_tactics_are_not_discounted(self) -> None:
        engine = make_engine()
        engine.on_signal(caller(K.AUTHORITY, 0.5, 1.0))
        engine.on_assessment(
            assessment(
                2.0, True, covered_seg_ids=frozenset({1}), listed_kinds=frozenset({K.AUTHORITY})
            )
        )
        components = engine.evaluate(3.0).components
        assert components is not None
        assert components.pressure == pytest.approx(0.25)


def test_dismissal_lasts_until_something_new_happens() -> None:
    engine = make_engine()
    end = play(engine, case("5 "))
    assert engine.evaluate(end).level is L.CRITICAL
    engine.dismiss(end)
    assert engine.evaluate(end + 1.0).dismissed
    engine.on_context(ContextEvent(t=end + 2.0, kind=C.BANK_PAGE))
    assert not engine.evaluate(end + 3.0).dismissed


def test_evidence_fades_during_speech_not_during_silence() -> None:
    engine = make_engine()
    engine.on_segment(Segment(session_id="s", seg_id=0, stream=Stream.CALLER, t_start=0.0,
                              t_end=5.0, text=""))  # fmt: skip
    end = play(engine, case("5 "))
    first = engine.evaluate(end)
    silent = engine.evaluate(1000.0)  # a long silent hold
    assert first.level is L.CRITICAL
    assert silent.level is L.CRITICAL
    assert silent.components is not None
    assert first.components is not None
    assert silent.components.pressure == pytest.approx(first.components.pressure, rel=0.01)
    engine.on_segment(Segment(session_id="s", seg_id=9, stream=Stream.CALLER, t_start=1000.0,
                              t_end=2800.0, text=""))  # fmt: skip
    talked = engine.evaluate(2800.0)  # three half-lives of speech later
    assert talked.components is not None
    assert talked.components.pressure < 0.25
    assert engine.evaluate(2831.0).level is L.QUIET  # after the hysteresis hold


def test_reasons_are_ordered_and_exclude_weak_evidence() -> None:
    engine = make_engine()
    state = engine.evaluate(play(engine, case("11 ")))
    assert [reason.label for reason in state.reasons] == ["money_request", "bank_page"]


def test_reset_returns_to_quiet() -> None:
    engine = make_engine()
    engine.evaluate(play(engine, case("5 ")))
    engine.reset()
    state = engine.evaluate(100.0)
    assert state.level is L.QUIET
    assert state.reasons == ()
    assert not state.llm_assessed


def test_state_reports_current_evidence_per_tactic() -> None:
    engine = make_engine()
    state = engine.evaluate(play(engine, case("4 ")))
    assert dict(state.evidence) == {K.AUTHORITY: 0.5, K.THREAT: 0.5, K.ISOLATION: 0.6}


def test_the_why_panel_keeps_every_reason_of_the_session() -> None:
    # A strong keyword starts at exactly min_evidence (0.5) and fades below it within
    # seconds of speech; the Why panel must still explain it.
    engine = make_engine()
    end = play(engine, case("4 "))  # authority .5, threat .5, isolation .6
    engine.on_segment(Segment(session_id="s", seg_id=9, stream=Stream.CALLER,
                              t_start=end, t_end=end + 60.0, text=""))  # fmt: skip
    state = engine.evaluate(end + 60.0)
    assert [reason.label for reason in state.reasons] == ["authority", "threat", "isolation"]


class TestCoercionLasts:
    """A confident coercive keyword keeps counting for minutes of speech, not seconds."""

    def test_a_threat_still_counts_after_twenty_seconds_of_talk(self) -> None:
        engine = make_engine()
        end = play(engine, case("10 "))  # threat .5 is the only coercion
        assert engine.evaluate(end).level is L.WARNING
        assert talk_and_tick(engine, end, 20.0).coercion

    def test_it_fades_out_after_several_minutes(self) -> None:
        engine = make_engine()
        end = play(engine, case("10 "))
        assert not talk_and_tick(engine, end, 600.0).coercion  # one half-life: 0.25

    def test_an_unconfident_signal_is_never_coercion(self) -> None:
        engine = make_engine()
        engine.on_assessment(assessment(0.0, True))
        engine.on_signal(
            Signal(
                t=1.0,
                kind=K.THREAT,
                source=SignalSource.LLM,
                tier=Tier.LLM,
                speaker=Stream.CALLER,
                confidence=0.4,
            )
        )
        assert not engine.evaluate(2.0).coercion
