"""Chaukas's alert copy."""

from __future__ import annotations

import pytest

from chaukas.ui.strings import ALERTS, alert_sentences

BLUEPRINT_KEYS = {
    "pause",
    "pressure",
    "authority_fact",
    "ignore_warning",
    "otp_pre",
    "otp_recovery",
    "remote",
    "verify",
}


def test_every_alert_from_the_blueprint_is_present() -> None:
    assert set(ALERTS) == BLUEPRINT_KEYS


@pytest.mark.parametrize("key", sorted(BLUEPRINT_KEYS))
def test_every_alert_has_english_and_hindi(key: str) -> None:
    alert = ALERTS[key]
    assert alert.text("en").strip()
    assert alert.text("hi").strip()
    assert alert.text("en") != alert.text("hi")


def test_sentences_are_split_at_full_stops_and_dandas() -> None:
    sentences = alert_sentences()
    assert "Pause before continuing." in sentences
    assert "आगे बढ़ने से पहले रुकें।" in sentences
    assert 'There is no such thing as a "digital arrest".' in sentences
    assert "Police, CBI or bank officials don't ask you to transfer money over a call." in sentences
    assert all(sentence == sentence.strip() and sentence for sentence in sentences)
