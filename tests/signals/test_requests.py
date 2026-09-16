from __future__ import annotations

import pytest

from chaukas.core.models import SignalKind
from chaukas.signals.lexicon import Lexicon
from chaukas.signals.normalise import tokenize
from chaukas.signals.requests import RequestHit, find_requests, inside_any

CREDENTIAL = SignalKind.CREDENTIAL_REQUEST


@pytest.fixture(scope="module")
def lexicon() -> Lexicon:
    return Lexicon.load()


def hits(lexicon: Lexicon, text: str, window: int = 6) -> list[RequestHit]:
    return find_requests(tokenize(text), lexicon, window=window)


def test_object_before_verb_hindi_order(lexicon: Lexicon) -> None:
    assert hits(lexicon, "OTP batao") == [RequestHit(CREDENTIAL, 0, 2, negated=False)]


def test_verb_before_object_english_order(lexicon: Lexicon) -> None:
    assert hits(lexicon, "tell me the OTP") == [RequestHit(CREDENTIAL, 0, 4, negated=False)]


@pytest.mark.parametrize(
    "text",
    [
        "we will never ask for your OTP",
        "do not share your OTP",
        "never ever share the password",  # one word allowed between negator and verb
        "OTP kisi ko mat batana",
        "OTP batana nahi",  # negator after the verb
    ],
)
def test_negated_verbs_make_protective_advice(lexicon: Lexicon, text: str) -> None:
    [hit] = hits(lexicon, text)
    assert hit.negated


def test_negation_further_away_does_not_count(lexicon: Lexicon) -> None:
    # "not" is three words before "share": the second clause is a real request.
    assert [hit.negated for hit in hits(lexicon, "do not tell anyone share the OTP")] == [False]


def test_distance_tie_prefers_the_non_negated_verb(lexicon: Lexicon) -> None:
    [hit] = hits(lexicon, "kisi ko mat batana otp batao")
    assert hit == RequestHit(CREDENTIAL, 4, 6, negated=False)


def test_objects_pair_only_with_verbs_of_their_kind(lexicon: Lexicon) -> None:
    # "download" is a remote-access verb; "otp" is a credential object.
    assert hits(lexicon, "download otp") == []


def test_window_limits_the_pairing(lexicon: Lexicon) -> None:
    text = "tell me one two three four five six seven words then the otp"
    assert hits(lexicon, text, window=3) == []


def test_excluded_spans_hide_objects(lexicon: Lexicon) -> None:
    tokens = tokenize("batao pin code")
    assert find_requests(tokens, lexicon, window=6, excluded=[(1, 3)]) == []


def test_inside_any() -> None:
    assert inside_any(2, 4, [(0, 1), (2, 5)])
    assert not inside_any(2, 6, [(2, 5)])
    assert not inside_any(0, 1, [])
