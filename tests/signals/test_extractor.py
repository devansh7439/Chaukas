"""Behaviour of the full extraction pipeline on realistic caller and user lines."""

from __future__ import annotations

import pytest

from chaukas.core.config import SignalsConfig, load_config
from chaukas.core.models import Segment, Signal, SignalKind, SignalSource, Stream, Tier
from chaukas.signals.extractor import SignalExtractor
from chaukas.signals.lexicon import Lexicon

K = SignalKind


@pytest.fixture(scope="module")
def lexicon() -> Lexicon:
    return Lexicon.load()


@pytest.fixture(scope="module")
def config() -> SignalsConfig:
    return load_config().signals


@pytest.fixture
def extractor(lexicon: Lexicon, config: SignalsConfig) -> SignalExtractor:
    return SignalExtractor(lexicon, config)


def segment(stream: Stream, text: str, t: float = 10.0, seg_id: int = 1) -> Segment:
    return Segment(
        session_id="s", seg_id=seg_id, stream=stream, t_start=t, t_end=t + 2.0, text=text
    )


def tiers(signals: list[Signal]) -> dict[SignalKind, Tier]:
    return {signal.kind: signal.tier for signal in signals}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Sir, CBI se bol raha hoon. Aapke naam pe arrest warrant hai.",
            {K.AUTHORITY: Tier.PHRASE, K.THREAT: Tier.STRONG},
        ),
        ("We will never ask for your OTP.", {}),
        ("Never share your OTP with anyone.", {}),
        ("OTP kisi ko mat batana", {}),
        ("Yeh baat kisi ko mat batana", {K.ISOLATION: Tier.PHRASE}),
        (
            "Kisi ko mat batana, OTP batao",
            {K.ISOLATION: Tier.PHRASE, K.CREDENTIAL_REQUEST: Tier.FAST_PATH},
        ),
        (
            "Don't tell anyone. Tell me the OTP now.",
            {K.ISOLATION: Tier.PHRASE, K.CREDENTIAL_REQUEST: Tier.FAST_PATH},
        ),
        ("Beta, OTP bata do", {K.CREDENTIAL_REQUEST: Tier.FAST_PATH}),
        ("Aapka pin code kya hai?", {}),
        ("आप अभी पैसे भेजो", {K.URGENCY: Tier.WEAK, K.MONEY_REQUEST: Tier.FAST_PATH}),
        ("You are under digital arrest", {K.SURVEILLANCE: Tier.PHRASE, K.THREAT: Tier.STRONG}),
        ("Please download AnyDesk now", {K.REMOTE_ACCESS_REQUEST: Tier.FAST_PATH}),
        ("Don't install AnyDesk", {}),
        ("Tell me the code on screen", {K.REMOTE_ACCESS_REQUEST: Tier.PHRASE}),
        (
            "The police arrested the suspect yesterday",
            {K.AUTHORITY: Tier.STRONG, K.THREAT: Tier.STRONG},
        ),
    ],
)
def test_caller_lines(
    extractor: SignalExtractor, text: str, expected: dict[SignalKind, Tier]
) -> None:
    assert tiers(extractor.extract(segment(Stream.CALLER, text))) == expected


def test_caller_signal_fields(extractor: SignalExtractor, config: SignalsConfig) -> None:
    [signal] = extractor.extract(segment(Stream.CALLER, "OTP batao", t=42.0, seg_id=7))
    assert signal == Signal(
        t=42.0,
        kind=K.CREDENTIAL_REQUEST,
        source=SignalSource.KEYWORD,
        tier=Tier.FAST_PATH,
        speaker=Stream.CALLER,
        confidence=config.fast_path,
        evidence="otp batao",
        seg_id=7,
    )


def test_signals_come_in_kind_order(extractor: SignalExtractor) -> None:
    kinds = [s.kind for s in extractor.extract(segment(Stream.CALLER, "arrest, CBI, OTP batao"))]
    assert kinds == [K.AUTHORITY, K.THREAT, K.CREDENTIAL_REQUEST]


def test_user_keywords_are_not_evidence(extractor: SignalExtractor) -> None:
    assert extractor.extract(segment(Stream.USER, "CBI arrest OTP batao")) == []


class TestUserDigitsRule:
    def test_code_read_out_after_a_credential_request(
        self, extractor: SignalExtractor, config: SignalsConfig
    ) -> None:
        extractor.extract(segment(Stream.CALLER, "OTP batao", t=10.0))
        [signal] = extractor.extract(segment(Stream.USER, "saat aath nau paanch", t=20.0))
        assert signal.kind is K.USER_DIGITS_SPOKEN
        assert signal.speaker is Stream.USER
        assert signal.confidence == config.digit_confidence
        assert not any(digit in signal.evidence for digit in "7895")  # the code is never stored
        assert signal.evidence == "user read out a 4-digit code"

    def test_no_request_no_signal(self, extractor: SignalExtractor) -> None:
        assert extractor.extract(segment(Stream.USER, "4 5 6 7")) == []

    def test_weak_request_does_not_arm_the_rule(self, extractor: SignalExtractor) -> None:
        extractor.extract(segment(Stream.CALLER, "Do you have an OTP?", t=10.0))  # strong: 0.5
        assert extractor.extract(segment(Stream.USER, "4567", t=15.0)) == []

    def test_request_older_than_the_lookback_is_forgotten(self, extractor: SignalExtractor) -> None:
        extractor.extract(segment(Stream.CALLER, "OTP batao", t=0.0))
        assert extractor.extract(segment(Stream.USER, "4567", t=100.0)) == []

    @pytest.mark.parametrize("text", ["9876543210", "98765 43210", "pin code 110001"])
    def test_other_numbers_are_not_codes(self, extractor: SignalExtractor, text: str) -> None:
        extractor.extract(segment(Stream.CALLER, "OTP batao", t=10.0))
        assert extractor.extract(segment(Stream.USER, text, t=12.0)) == []

    def test_observe_accepts_requests_from_other_detectors(
        self, extractor: SignalExtractor
    ) -> None:
        extractor.observe(
            Signal(
                t=5.0,
                kind=K.CREDENTIAL_REQUEST,
                source=SignalSource.LLM,
                tier=Tier.LLM,
                speaker=Stream.CALLER,
                confidence=0.8,
            )
        )
        assert len(extractor.extract(segment(Stream.USER, "4567", t=10.0))) == 1

    def test_reset_forgets_requests(self, extractor: SignalExtractor) -> None:
        extractor.extract(segment(Stream.CALLER, "OTP batao", t=10.0))
        extractor.reset()
        assert extractor.extract(segment(Stream.USER, "4567", t=12.0)) == []
