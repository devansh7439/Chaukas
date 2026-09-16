from __future__ import annotations

import unicodedata

import pytest

from chaukas.signals.normalise import normalise, tokenize


def test_casefolds_latin_and_splits_on_punctuation() -> None:
    assert tokenize("Sir, CBI se bol raha hoon!") == ["sir", "cbi", "se", "bol", "raha", "hoon"]


def test_devanagari_words_keep_vowel_signs_and_lose_dandas() -> None:
    assert tokenize("आप अभी पैसे भेजो। कैमरा चालू रखें॥") == [
        "आप",
        "अभी",
        "पैसे",
        "भेजो",
        "कैमरा",
        "चालू",
        "रखें",
    ]


def test_nfc_makes_decomposed_and_composed_forms_equal() -> None:
    composed = "पाँच"
    decomposed = unicodedata.normalize("NFD", composed)
    assert tokenize(decomposed) == tokenize(composed)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Don't tell anyone", "do not tell anyone"),
        ("don’t disconnect", "do not disconnect"),
        ("dont cut the call", "do not cut the call"),
        ("we won't ask", "we will not ask"),
        ("you can't leave", "you can not leave"),
        ("it isn't legal", "it is not legal"),
        ("your account's frozen", "your account frozen"),
    ],
)
def test_contractions_expand_so_negation_is_a_token(text: str, expected: str) -> None:
    assert normalise(text) == expected


def test_devanagari_digits_become_ascii() -> None:
    assert tokenize("पिन ११०००१") == ["पिन", "110001"]


def test_rupee_sign_is_a_token() -> None:
    assert tokenize("₹50000 bhejo") == ["₹", "50000", "bhejo"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my otp is four five six seven", "my otp is 4 5 6 7"),
        ("ek do teen char", "1 2 3 4"),
        ("double five one two", "5 5 1 2"),
        ("चार पांच छह सात", "4 5 6 7"),
        ("four oh four", "4 0 4"),
    ],
)
def test_spoken_digit_sequences_become_digits(text: str, expected: str) -> None:
    assert normalise(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "one time password",  # a single number word is not a digit sequence
        "do not tell anyone",  # 'do' is ambiguous and has no unambiguous neighbour
        "paise bhej do 5000",  # one number word next to digits is not converted
        "sat down",
    ],
)
def test_ordinary_phrases_with_number_words_are_left_alone(text: str) -> None:
    assert normalise(text) == text


def test_empty_and_punctuation_only_input() -> None:
    assert tokenize("") == []
    assert tokenize(" ... !!! ") == []
