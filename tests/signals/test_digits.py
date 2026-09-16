from __future__ import annotations

import pytest

from chaukas.signals.digits import DigitRun, find_codes


def codes(tokens: list[str], **kwargs: object) -> list[DigitRun]:
    return find_codes(tokens, min_digits=4, max_digits=8, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["4567"], [DigitRun(0, 1, 4)]),
        (["mera", "otp", "4", "5", "6", "7"], [DigitRun(2, 6, 4)]),
        (["45", "67", "89"], [DigitRun(0, 3, 6)]),
        (["12345678"], [DigitRun(0, 1, 8)]),
    ],
)
def test_accepts_codes_of_four_to_eight_digits(tokens: list[str], expected: list[DigitRun]) -> None:
    assert codes(tokens) == expected


@pytest.mark.parametrize(
    "tokens",
    [
        ["123"],  # too short
        ["9876543210"],  # phone number
        ["98765", "43210"],  # phone number split by ASR
        ["1234", "5678", "9012"],  # 12 digits: Aadhaar-like
        ["no", "digits", "here"],
    ],
)
def test_rejects_other_numbers(tokens: list[str]) -> None:
    assert codes(tokens) == []


def test_separate_runs_are_evaluated_independently() -> None:
    assert codes(["otp", "4567", "amount", "50000", "phone", "9876543210"]) == [
        DigitRun(1, 2, 4),
        DigitRun(3, 4, 5),
    ]


def test_runs_right_after_an_excluded_phrase_are_skipped() -> None:
    tokens = ["pin", "code", "is", "110001", "otp", "4567"]
    assert codes(tokens, excluded_ends=[2]) == [DigitRun(5, 6, 4)]


def test_non_ascii_digit_like_tokens_are_not_codes() -> None:
    assert codes(["१२३४"]) == []
