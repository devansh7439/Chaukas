"""Behaviour of the full extraction pipeline on realistic caller and user lines."""

from __future__ import annotations

import pytest

from chaukas.core.config import SignalsConfig, load_config
from chaukas.core.models import Segment, Signal, SignalKind, SignalSource, Stream, Tier
from chaukas.signals.extractor import SignalExtractor
from chaukas.signals.lexicon import Lexicon
from chaukas.ui.strings import alert_sentences

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


@pytest.mark.parametrize("sentence", alert_sentences())
def test_chaukas_own_alerts_heard_through_loopback_are_not_evidence(
    extractor: SignalExtractor, sentence: str
) -> None:
    assert extractor.extract(segment(Stream.CALLER, sentence)) == []


def test_an_alert_quoted_inside_real_speech_suppresses_only_itself(
    extractor: SignalExtractor,
) -> None:
    text = "Never share an OTP with anyone who calls you. Ab OTP batao."
    kinds = {signal.kind for signal in extractor.extract(segment(Stream.CALLER, text))}
    assert kinds == {K.CREDENTIAL_REQUEST}


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Install any desk so I can check your computer.", K.REMOTE_ACCESS_REQUEST),
        ("Download team viewer from the website.", K.REMOTE_ACCESS_REQUEST),
        ("Open rust desk and tell me the code.", K.REMOTE_ACCESS_REQUEST),
        ("I am calling from the CBI Cybercell.", K.AUTHORITY),
    ],
)
def test_spellings_whisper_actually_produces(
    extractor: SignalExtractor, text: str, kind: SignalKind
) -> None:
    kinds = {signal.kind for signal in extractor.extract(segment(Stream.CALLER, text))}
    assert kind in kinds


class TestCallerCannotForgeAdvice:
    """Red-team regression: a negation the caller puts in front of a request ("don't worry",
    "no,") must not turn the request into protective advice and hide the OTP keyword."""

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("No, just read out the OTP.", K.CREDENTIAL_REQUEST),
            ("No no, share the OTP now.", K.CREDENTIAL_REQUEST),
            ("Don't panic, share the OTP quickly.", K.CREDENTIAL_REQUEST),
            ("Don't worry, send the OTP.", K.CREDENTIAL_REQUEST),
            ("don't worry send the OTP", K.CREDENTIAL_REQUEST),  # no punctuation from ASR
            ("Nahi nahi, OTP batao.", K.CREDENTIAL_REQUEST),
            ("nahi nahi OTP batao", K.CREDENTIAL_REQUEST),
            ("Mat ghabraiye, OTP bataiye.", K.CREDENTIAL_REQUEST),
            ("No, no, install AnyDesk.", K.REMOTE_ACCESS_REQUEST),
            ("Don't worry, transfer the amount.", K.MONEY_REQUEST),
        ],
    )
    def test_reassurance_before_a_request_keeps_the_request(
        self, extractor: SignalExtractor, text: str, kind: SignalKind
    ) -> None:
        assert tiers(extractor.extract(segment(Stream.CALLER, text))).get(kind) is Tier.FAST_PATH

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            (
                "Never share an OTP with anyone who calls you, even if they say they are "
                "from your bank, OTP batao",
                K.CREDENTIAL_REQUEST,
            ),
            (
                "Police, CBI or bank officials don't ask you to transfer money over a call. "
                "So transfer the money to me now.",
                K.MONEY_REQUEST,
            ),
        ],
    )
    def test_reciting_chaukas_own_alert_cannot_hide_a_request_beside_it(
        self, extractor: SignalExtractor, text: str, kind: SignalKind
    ) -> None:
        # Chaukas's alert sentences are suppressed as evidence; the span is verbatim only.
        assert kind in tiers(extractor.extract(segment(Stream.CALLER, text)))

    @pytest.mark.parametrize(
        "text",
        [
            "Please never ever share your OTP.",
            "Do not share the OTP with anyone.",
            "Kabhi bhi OTP mat batana.",
            "Never, ever share your OTP.",  # a comma inside the advice itself
        ],
    )
    def test_real_advice_is_still_advice(self, extractor: SignalExtractor, text: str) -> None:
        assert K.CREDENTIAL_REQUEST not in tiers(extractor.extract(segment(Stream.CALLER, text)))


class TestHindiCompounds:
    """Red-team regressions in Hinglish: a negator after the verb negates it only when a
    helper verb or the end of the clause follows ("share mat karna", "batana nahi"); in
    "batao nahi toh ..." the "nahi" means "otherwise". Polite compounds ("bata dijiye",
    "confirm kariye") are the verb itself."""

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("OTP batao nahi toh account band ho jayega", K.CREDENTIAL_REQUEST),
            ("Abhi OTP batana nahi to arrest hoga", K.CREDENTIAL_REQUEST),
            ("Paise bhejo nahi to case darj hoga", K.MONEY_REQUEST),
            ("OTP batao mat ghabrao", K.CREDENTIAL_REQUEST),
            ("OTP bata dijiye", K.CREDENTIAL_REQUEST),
            ("OTP bhej dijiye", K.CREDENTIAL_REQUEST),
            ("OTP confirm kariye", K.CREDENTIAL_REQUEST),
            ("Jo code aaya hai woh confirm kar dijiye", K.CREDENTIAL_REQUEST),
            ("Paise jama kar dijiye", K.MONEY_REQUEST),
            ("AnyDesk install kar lijiye", K.REMOTE_ACCESS_REQUEST),
        ],
    )
    def test_requests(self, extractor: SignalExtractor, text: str, kind: SignalKind) -> None:
        assert tiers(extractor.extract(segment(Stream.CALLER, text))).get(kind) is Tier.FAST_PATH

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("OTP share mat karna", K.CREDENTIAL_REQUEST),
            ("OTP kisi ke saath share mat kijiye", K.CREDENTIAL_REQUEST),
            ("OTP batana nahi hai", K.CREDENTIAL_REQUEST),
            ("OTP kisi ko batana nahi chahiye", K.CREDENTIAL_REQUEST),
            ("Paise kisi ko transfer mat karna", K.MONEY_REQUEST),
            ("AnyDesk install mat karna", K.REMOTE_ACCESS_REQUEST),
            ("OTP batana mat", K.CREDENTIAL_REQUEST),
        ],
    )
    def test_advice(self, extractor: SignalExtractor, text: str, kind: SignalKind) -> None:
        assert kind not in tiers(extractor.extract(segment(Stream.CALLER, text)))


class TestOffers:
    """The speaker sending something is an offer, not a request: "we will send an OTP to
    your registered mobile" was a full-strength credential request."""

    @pytest.mark.parametrize(
        "text",
        [
            "We will send an OTP to your registered mobile.",
            "I am sending you an OTP now.",
            "Hum aapko OTP bhej rahe hain.",
            "I will share my screen so you can follow along.",
        ],
    )
    def test_the_speaker_sending_is_not_a_request(
        self, extractor: SignalExtractor, text: str
    ) -> None:
        found = tiers(extractor.extract(segment(Stream.CALLER, text)))
        assert Tier.FAST_PATH not in found.values()

    @pytest.mark.parametrize(
        "text",
        [
            "Send me the OTP.",
            "We need you to send the OTP.",
            "I will send you a link, then send the OTP to this number.",
            "We have sent the OTP, please read it out to me.",
            "We will send you an OTP, send it back to me.",
        ],
    )
    def test_requests_around_an_offer_are_still_requests(
        self, extractor: SignalExtractor, text: str
    ) -> None:
        found = tiers(extractor.extract(segment(Stream.CALLER, text)))
        assert found.get(K.CREDENTIAL_REQUEST) is Tier.FAST_PATH


@pytest.mark.parametrize(
    "text",
    [
        "Install this utility so I can complete the refund.",
        "Download the support tool from the link I sent.",
        "Please install the apk I sent on WhatsApp.",
        "Share your screen with me.",
    ],
)
def test_install_requests_name_the_software_generically(
    extractor: SignalExtractor, text: str
) -> None:
    found = tiers(extractor.extract(segment(Stream.CALLER, text)))
    assert found.get(K.REMOTE_ACCESS_REQUEST) is Tier.FAST_PATH


class TestOrganisationClaims:
    """Review follow-up (RT11 analysis): "I am from the refunds team of your electricity
    company" named no known agency, so the remote-banking rule, which needs an organisation
    claim, never fired. A self-introduction on behalf of an organisation is now a weak
    authority signal: enough for that rule, too weak to prime the OTP rule or fill a step."""

    @pytest.mark.parametrize(
        "text",
        [
            "Good afternoon, I am from the refunds team of your electricity company.",
            "This is Rahul calling from the billing department.",
            "We are from the security desk of your internet provider.",
            "Main insurance company ke claims department se bol rahi hoon.",
        ],
    )
    def test_introductions_for_an_organisation_are_a_weak_claim(
        self, extractor: SignalExtractor, text: str
    ) -> None:
        assert tiers(extractor.extract(segment(Stream.CALLER, text))).get(K.AUTHORITY) is Tier.WEAK

    @pytest.mark.parametrize(
        "text",
        [
            "I am from Delhi, just visiting for the weekend.",
            "This is my friend from school.",
            "I am calling from the clinic about your appointment.",
            "The team from the other company won the match.",
        ],
    )
    def test_other_introductions_are_not(self, extractor: SignalExtractor, text: str) -> None:
        assert K.AUTHORITY not in tiers(extractor.extract(segment(Stream.CALLER, text)))


@pytest.mark.parametrize(
    "text",
    ["Please install any disk on your laptop.", "Download any disk and tell me the number."],
)
def test_whisper_hears_anydesk_as_any_disk(extractor: SignalExtractor, text: str) -> None:
    # Measured: Whisper small transcribed a spoken "AnyDesk" as "any disk" (tools/audio_eval.py).
    found = tiers(extractor.extract(segment(Stream.CALLER, text)))
    assert K.REMOTE_ACCESS_REQUEST in found
