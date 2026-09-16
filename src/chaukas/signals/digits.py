"""Find spoken codes in a user's segment, for the user-digits (recovery) rule.

A code is a maximal run of adjacent digit tokens totalling ``min_digits``–``max_digits``
digits: "4567", "4 5 6 7" and "45 67" all qualify. Longer runs are phone, account or Aadhaar
numbers, not OTPs. A run starting right after a suppressed phrase ("pin code is 110001")
is a postal code. Only the length is kept: the digits themselves never leave this function.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DigitRun:
    start: int
    end: int
    length: int  # number of digits; the digits are deliberately not stored


def find_codes(
    tokens: Sequence[str],
    *,
    min_digits: int,
    max_digits: int,
    excluded_ends: Sequence[int] = (),
    lookahead: int = 2,
) -> list[DigitRun]:
    """Digit runs of acceptable length that don't start within ``lookahead`` tokens after
    the end of an excluded phrase."""
    runs: list[DigitRun] = []
    i, n = 0, len(tokens)
    while i < n:
        if not _is_digits(tokens[i]):
            i += 1
            continue
        j = i
        while j < n and _is_digits(tokens[j]):
            j += 1
        length = sum(len(token) for token in tokens[i:j])
        after_excluded = any(0 <= i - end <= lookahead for end in excluded_ends)
        if min_digits <= length <= max_digits and not after_excluded:
            runs.append(DigitRun(i, j, length))
        i = j
    return runs


def _is_digits(token: str) -> bool:
    return token.isascii() and token.isdigit()
