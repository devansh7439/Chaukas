from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chaukas.core.errors import ConfigError
from chaukas.core.models import SignalKind, Tier
from chaukas.signals.lexicon import Lexicon, Term
from chaukas.signals.normalise import tokenize


@pytest.fixture(scope="module")
def lexicon() -> Lexicon:
    return Lexicon.load()


def terms_in(lexicon: Lexicon, text: str) -> set[tuple[SignalKind, Tier, str]]:
    return {
        (m.payload.kind, m.payload.tier, m.payload.text) for m in lexicon.terms.find(tokenize(text))
    }


def minimal_spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "version": 1,
        "tactics": {"threat": {"terms": ["arrest"]}},
        "requests": {"credential_request": {"verbs": ["tell"], "objects": ["otp"]}},
        "negation": {"gap": 1, "before": ["not"], "after": []},
        "suppress": ["pin code"],
    }
    spec.update(overrides)
    return spec


class TestPackagedLexicon:
    def test_single_words_are_strong_and_phrases_are_phrase_tier(self, lexicon: Lexicon) -> None:
        found = terms_in(lexicon, "share your one time password or otp")
        assert (SignalKind.CREDENTIAL_REQUEST, Tier.PHRASE, "one time password") in found
        assert (SignalKind.CREDENTIAL_REQUEST, Tier.STRONG, "otp") in found

    def test_weak_terms(self, lexicon: Lexicon) -> None:
        assert terms_in(lexicon, "abhi karo") == {(SignalKind.URGENCY, Tier.WEAK, "abhi")}

    def test_devanagari_terms_ending_in_vowel_signs_match(self, lexicon: Lexicon) -> None:
        found = terms_in(lexicon, "आप अभी कैमरा चालू रखें")
        assert (SignalKind.URGENCY, Tier.WEAK, "अभी") in found
        assert (SignalKind.SURVEILLANCE, Tier.PHRASE, "कैमरा चालू रखें") in found

    def test_contractions_in_terms_match_either_spelling(self, lexicon: Lexicon) -> None:
        expected = (SignalKind.ISOLATION, Tier.PHRASE, "do not tell anyone")
        assert expected in terms_in(lexicon, "Don't tell anyone")
        assert expected in terms_in(lexicon, "do not tell anyone")

    def test_english_inflections_match(self, lexicon: Lexicon) -> None:
        assert (SignalKind.THREAT, Tier.STRONG, "arrest") in terms_in(lexicon, "you are arrested")
        verbs = {(m.payload.kind, m.payload.role) for m in lexicon.request_words.find(["sharing"])}
        assert (SignalKind.CREDENTIAL_REQUEST, "verb") in verbs

    def test_negators_and_suppressions_are_compiled(self, lexicon: Lexicon) -> None:
        assert {"not", "never", "mat", "नहीं"} <= lexicon.negators_before
        assert [m.payload for m in lexicon.suppressions.find(tokenize("PIN code"))] == ["pin code"]


class TestValidation:
    def test_minimal_spec_compiles(self) -> None:
        lexicon = Lexicon.from_mapping(minimal_spec())
        [match] = lexicon.terms.find(["arrest"])
        assert match.payload == Term(SignalKind.THREAT, Tier.STRONG, "arrest")

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"version": 2}, "version"),
            ({"tactics": {"user_digits_spoken": {"terms": ["x"]}}}, "comes from a rule"),
            ({"requests": {"threat": {"verbs": ["a"], "objects": ["b"]}}}, "request kinds"),
            ({"requests": {"credential_request": {"verbs": [], "objects": ["b"]}}}, "verbs"),
            ({"colour": "red"}, "Extra inputs"),
        ],
    )
    def test_schema_errors(self, overrides: dict[str, Any], message: str) -> None:
        with pytest.raises(ConfigError, match=message):
            Lexicon.from_mapping(minimal_spec(**overrides))

    def test_entry_that_normalises_to_nothing(self) -> None:
        with pytest.raises(ConfigError, match="empty after normalisation"):
            Lexicon.from_mapping(minimal_spec(suppress=["!!!"]))

    def test_multi_word_negator(self) -> None:
        spec = minimal_spec(negation={"gap": 1, "before": ["don't"], "after": []})
        with pytest.raises(ConfigError, match="single word"):
            Lexicon.from_mapping(spec)

    def test_file_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="cannot read"):
            Lexicon.load(tmp_path / "missing.yaml")
        bad = tmp_path / "bad.yaml"
        bad.write_text("tactics: [unclosed", encoding="utf-8")
        with pytest.raises(ConfigError, match="not valid YAML"):
            Lexicon.load(bad)
        listing = tmp_path / "list.yaml"
        listing.write_text("- a\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="mapping"):
            Lexicon.load(listing)
