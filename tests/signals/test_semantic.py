"""Semantic detection: what a caller line *means*, for paraphrases the lexicon misses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

np = pytest.importorskip("numpy")

from chaukas.core.config import load_config  # noqa: E402
from chaukas.core.models import Segment, SignalKind, SignalSource, Stream, Tier  # noqa: E402
from chaukas.signals.semantic import Intents, SemanticDetector  # noqa: E402

K = SignalKind
CONFIG = load_config().signals.semantic


class TableEmbedder:
    """A fake embedder: each known sentence maps to a fixed unit vector."""

    def __init__(self, table: Mapping[str, Sequence[float]]) -> None:
        self.table = {text: np.asarray(v, dtype=np.float32) / np.linalg.norm(v)
                      for text, v in table.items()}  # fmt: skip
        self.calls = 0
        self.batch_sizes: list[int] = []

    def embed(self, texts: Sequence[str]) -> object:
        self.calls += 1
        self.batch_sizes.append(len(texts))
        return np.stack([self.table[text] for text in texts])


INTENTS = Intents(
    means={K.CREDENTIAL_REQUEST: ("tell me the code you received",),
           K.THREAT: ("you will be arrested",)},
    not_={K.CREDENTIAL_REQUEST: ("never share your code with anyone",)},
)  # fmt: skip
TABLE = {
    "tell me the code you received": [1, 0, 0, 0],
    "you will be arrested": [0, 1, 0, 0],
    "never share your code with anyone": [0.6, 0, 0.8, 0],
    # caller lines
    "read me the digits we sent you": [0.95, 0, 0.1, 0.3],
    "do not give the digits to anybody": [0.55, 0, 0.83, 0],
    "the meeting is at five": [0, 0, 0, 1],
    "police will take you away tonight": [0, 0.9, 0, 0.43],
}


def detector() -> SemanticDetector:
    return SemanticDetector(TableEmbedder(TABLE), INTENTS, CONFIG)


def caller(text: str, stream: Stream = Stream.CALLER) -> Segment:
    return Segment(session_id="s", seg_id=3, stream=stream, t_start=4.0, t_end=6.0, text=text)


class TestSemanticDetector:
    def test_a_paraphrased_request_becomes_a_semantic_signal(self) -> None:
        (signal,) = detector().detect(caller("read me the digits we sent you"))
        assert signal.kind is K.CREDENTIAL_REQUEST
        assert signal.source is SignalSource.SEMANTIC
        assert signal.tier is Tier.SEMANTIC
        assert signal.confidence == CONFIG.request_confidence
        assert signal.t == 4.0
        assert signal.seg_id == 3
        assert "tell me the code you received" in signal.evidence

    def test_advice_that_resembles_the_request_more_than_the_request_is_not_one(self) -> None:
        assert detector().detect(caller("do not give the digits to anybody")) == []

    def test_unrelated_speech_gives_nothing(self) -> None:
        assert detector().detect(caller("the meeting is at five")) == []

    def test_tactics_get_the_tactic_confidence(self) -> None:
        (signal,) = detector().detect(caller("police will take you away tonight"))
        assert signal.kind is K.THREAT
        assert signal.confidence == CONFIG.tactic_confidence

    def test_the_users_own_words_are_never_semantic_evidence(self) -> None:
        assert detector().detect(caller("read me the digits we sent you", Stream.USER)) == []

    def test_the_examples_are_embedded_once(self) -> None:
        embedder = TableEmbedder(TABLE)
        semantic = SemanticDetector(embedder, INTENTS, CONFIG)
        examples = embedder.calls
        assert examples == 3  # each example once, at construction
        semantic.detect(caller("the meeting is at five"))
        semantic.detect(caller("read me the digits we sent you"))
        assert embedder.calls == examples + 2  # then one call per line

    def test_every_text_is_embedded_alone_like_a_live_line(self) -> None:
        # The int8 model quantises activations per batch: a sentence's vector shifted by
        # ~0.003 cosine with the other examples in its batch, so adding one example moved
        # every decision. Examples are embedded one at a time, exactly like live lines.
        embedder = TableEmbedder(TABLE)
        SemanticDetector(embedder, INTENTS, CONFIG).detect(caller("the meeting is at five"))
        assert set(embedder.batch_sizes) == {1}

    def test_requests_are_strong_enough_for_the_otp_rule(self) -> None:
        rules = load_config().engine.rules
        assert CONFIG.request_confidence >= rules.pre_disclosure_min_confidence
        assert CONFIG.tactic_confidence >= rules.min_evidence


class TestExtractorIntegration:
    def test_semantic_signals_join_keyword_signals_and_feed_the_digit_rule(self) -> None:
        from chaukas.signals.extractor import SignalExtractor
        from chaukas.signals.lexicon import Lexicon

        extractor = SignalExtractor(Lexicon.load(), load_config().signals, semantic=detector())
        kinds = [s.kind for s in extractor.extract(caller("read me the digits we sent you"))]
        assert kinds == [K.CREDENTIAL_REQUEST]
        user = Segment(session_id="s", seg_id=4, stream=Stream.USER, t_start=7.0, t_end=9.0,
                       text="four five six seven")  # fmt: skip
        assert [s.kind for s in extractor.extract(user)] == [K.USER_DIGITS_SPOKEN]

    def test_the_stronger_of_keyword_and_semantic_wins(self) -> None:
        from chaukas.signals.extractor import SignalExtractor
        from chaukas.signals.lexicon import Lexicon

        table = dict(TABLE)
        table["Tell me the OTP now."] = [0.97, 0, 0, 0.24]
        semantic = SemanticDetector(TableEmbedder(table), INTENTS, CONFIG)
        extractor = SignalExtractor(Lexicon.load(), load_config().signals, semantic=semantic)
        (signal,) = extractor.extract(caller("Tell me the OTP now."))
        assert signal.kind is K.CREDENTIAL_REQUEST
        assert signal.source is SignalSource.KEYWORD  # fast path 0.75 beats semantic 0.7
