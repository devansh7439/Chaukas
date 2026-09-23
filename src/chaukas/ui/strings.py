"""Chaukas's alert copy (blueprint 6.8), in English and Hindi.

Plain data with no Qt dependency, so the signal extractor can load it too. Every sentence
here is a suppression phrase: if a spoken alert leaks back through loopback as caller
audio, it never counts as evidence. This is the second line of defence after the
playback guard (blueprint 6.1).

The Hindi copy must be reviewed by a native speaker before recording (blueprint 13).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

Language = Literal["en", "hi"]

# A sentence ends at . ! ? or a danda, optionally followed by a closing quote.
_SENTENCE_END: Final = re.compile(r"(?<=[.!?।])\s+")


@dataclass(frozen=True, slots=True)
class AlertText:
    en: str
    hi: str

    def text(self, language: Language) -> str:
        return self.en if language == "en" else self.hi


ALERTS: Final[Mapping[str, AlertText]] = MappingProxyType(
    {
        "pause": AlertText(
            en="Pause before continuing.",
            hi="आगे बढ़ने से पहले रुकें।",
        ),
        "pressure": AlertText(
            en="Someone on your call may be pressuring you. Take a moment before you act.",
            hi="कॉल पर कोई आप पर दबाव डाल रहा हो सकता है। कुछ भी करने से पहले एक पल रुकें।",
        ),
        "authority_fact": AlertText(
            en='There is no such thing as a "digital arrest". Police, CBI or bank officials '
            "don't ask you to transfer money over a call.",
            hi='"डिजिटल अरेस्ट" जैसी कोई चीज़ नहीं होती। पुलिस, सीबीआई या बैंक अधिकारी कॉल पर '
            "पैसे ट्रांसफर करने को नहीं कहते।",
        ),
        "ignore_warning": AlertText(
            en="If the caller tells you to ignore this warning, that is another warning sign.",
            hi="अगर कॉल करने वाला आपसे इस चेतावनी को अनदेखा करने को कहे, तो यह भी धोखाधड़ी का संकेत है।",
        ),
        "otp_pre": AlertText(
            en="Never share an OTP with anyone who calls you, even if they say they are from "
            "your bank.",
            hi="किसी भी कॉल करने वाले को OTP न बताएं, चाहे वह खुद को बैंक का अधिकारी बताए।",
        ),
        "otp_recovery": AlertText(
            en="If you already shared the OTP, call your bank now using the number printed on "
            "your card, and change your passwords.",
            hi="अगर आपने OTP बता दिया है, तो अभी अपने कार्ड पर छपे नंबर से बैंक को कॉल करें और "
            "अपने पासवर्ड बदलें।",
        ),
        "remote": AlertText(
            en="Someone on your call asked you to install remote-access software. This can "
            "give them control of your computer.",
            hi="कॉल पर किसी ने आपसे रिमोट-एक्सेस सॉफ़्टवेयर इंस्टॉल करने को कहा है। इससे उन्हें "
            "आपके कंप्यूटर का नियंत्रण मिल सकता है।",
        ),
        "verify": AlertText(
            en="Hang up and contact the organisation using a number you find yourself.",
            hi="कॉल काटें और संस्था का नंबर खुद ढूँढकर उसी पर संपर्क करें।",
        ),
    }
)


def alert_sentences() -> tuple[str, ...]:
    """Every sentence of every alert in both languages, in a stable order."""
    sentences: list[str] = []
    for alert in ALERTS.values():
        for text in (alert.en, alert.hi):
            sentences.extend(part.strip() for part in _SENTENCE_END.split(text) if part.strip())
    return tuple(sentences)
