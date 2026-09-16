"""Text normalisation and tokenisation, shared by transcripts and the lexicon.

Lexicon terms pass through exactly the same pipeline as ASR output, so a term written once
in ``lexicon.yaml`` matches regardless of case, Unicode form, apostrophe style, contraction
or spoken-number form in the transcript.

Steps:
1. Unicode NFC, then casefold (lower-cases Latin; Devanagari is unaffected).
2. Unify apostrophes; map Devanagari digits to ASCII.
3. Tokenise into words. Devanagari vowel signs, virama and joiners stay inside words;
   dandas and other punctuation separate them. ``₹`` is its own token.
4. Expand contractions ("don't" → "do not"), so negation always appears as its own token.
5. Convert spoken digit sequences ("four five six seven", "ek do teen char") to digits.
   A run converts only when it has at least two number words, at least one of them
   unambiguous. "one time password", "do not" and "bhej do 5000" stay unchanged.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

_APOSTROPHES: Final = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})
_DEVANAGARI_DIGITS: Final = str.maketrans("०१२३४५६७८९", "0123456789")

# Letters/digits (\w), Devanagari block without the dandas (U+0964-5) and digits
# (already mapped to ASCII), zero-width (non-)joiners; optional internal apostrophes.
_WORD_CHARS: Final = r"\wऀ-ॣ॰-ॿ‌‍"
_TOKEN: Final = re.compile(rf"₹|[{_WORD_CHARS}]+(?:'[{_WORD_CHARS}]+)*")

_CONTRACTIONS: Final[dict[str, tuple[str, ...]]] = {
    "won't": ("will", "not"),
    "can't": ("can", "not"),
    "cannot": ("can", "not"),
    "shan't": ("shall", "not"),
    "dont": ("do", "not"),
    "didnt": ("did", "not"),
    "doesnt": ("does", "not"),
}

# Number words that are also ordinary words need an unambiguous neighbour to convert.
_UNAMBIGUOUS_NUMBERS: Final[dict[str, str]] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "shunya": "0", "shoonya": "0", "ek": "1", "teen": "3", "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5", "chhe": "6", "chheh": "6", "saat": "7", "aath": "8",
    "nau": "9",
    "शून्य": "0", "एक": "1", "तीन": "3", "चार": "4", "पांच": "5",
    "पाँच": "5", "छह": "6", "छः": "6", "सात": "7", "आठ": "8", "नौ": "9",
}  # fmt: skip
# "do"/"दो" also mean "give" ("bhej do"), "sat"/"tin"/"oh" are English words.
_AMBIGUOUS_NUMBERS: Final[dict[str, str]] = {
    "oh": "0", "do": "2", "दो": "2", "tin": "3", "sat": "7",
}  # fmt: skip
_MULTIPLIERS: Final[dict[str, int]] = {"double": 2, "triple": 3}


def tokenize(text: str) -> list[str]:
    """Normalise ``text`` and split it into tokens."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = text.translate(_APOSTROPHES).translate(_DEVANAGARI_DIGITS)
    tokens: list[str] = []
    for raw in _TOKEN.findall(text):
        tokens.extend(_expand_contraction(raw))
    return _convert_number_runs(tokens)


def normalise(text: str) -> str:
    """Normalised text: tokens joined by single spaces."""
    return " ".join(tokenize(text))


def _expand_contraction(token: str) -> tuple[str, ...]:
    if token in _CONTRACTIONS:
        return _CONTRACTIONS[token]
    if token.endswith("n't") and len(token) > 3:
        return (token[:-3], "not")
    if "'" in token:
        stem = token[:-2] if token.endswith("'s") else token
        return (stem.replace("'", ""),)
    return (token,)


def _is_numberish(token: str) -> bool:
    return (
        token.isdigit()
        or token in _UNAMBIGUOUS_NUMBERS
        or token in _AMBIGUOUS_NUMBERS
        or token in _MULTIPLIERS
    )


def _convert_number_runs(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if not _is_numberish(tokens[i]):
            out.append(tokens[i])
            i += 1
            continue
        j = i
        while j < len(tokens) and _is_numberish(tokens[j]):
            j += 1
        out.extend(_convert_run(tokens[i:j]))
        i = j
    return out


def _convert_run(run: list[str]) -> list[str]:
    words = [t for t in run if not t.isdigit()]
    has_anchor = any(t in _UNAMBIGUOUS_NUMBERS or t in _MULTIPLIERS for t in words)
    if len(words) < 2 or not has_anchor:
        return run
    out: list[str] = []
    repeat = 1
    for token in run:
        if token in _MULTIPLIERS:
            repeat = _MULTIPLIERS[token]
            continue
        digit = token if token.isdigit() else _UNAMBIGUOUS_NUMBERS.get(token)
        if digit is None:
            digit = _AMBIGUOUS_NUMBERS[token]
        out.extend([digit] * repeat)
        repeat = 1
    return out
