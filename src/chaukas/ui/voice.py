"""Spoken alerts: when the level rises to a warning or higher, Chaukas says why, out loud.

Someone on a frightening call may not be looking at the screen. So on each rise to a
warning, a critical or the recovery level, Chaukas speaks the matching alert text (the same
sentences as on the cards, in the dashboard's language when a voice for it is installed,
else in English). A notice is not spoken, nothing is repeated while the level holds, and
nothing is said on the way down.

Chaukas never reacts to its own voice: the loopback hears what the speakers play, and every
sentence of every alert is suppressed as evidence by the lexicon (tested sentence by
sentence in tests/ui/test_voice.py).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import Any, Final

from PySide6.QtCore import QObject

from chaukas.core.models import Level
from chaukas.ui.copy import Language
from chaukas.ui.strings import ALERTS

_FACT_BY_OBJECTIVE: Final[Mapping[str, str]] = {
    "money_transfer": "authority_fact",
    "credential_disclosure": "otp_pre",
    "remote_control": "remote",
}


def spoken_alert(previous: Level, current: Level, objective: str, language: Language) -> str | None:
    """What to say when the level goes from ``previous`` to ``current``, or None."""
    if current <= previous or current < Level.WARNING:
        return None

    def say(key: str) -> str:
        text: str = getattr(ALERTS[key], language)
        return text

    if current is Level.CRITICAL_RECOVERY:
        return say("otp_recovery")
    if current is Level.CRITICAL:
        return f"{say('pause')} {say(_FACT_BY_OBJECTIVE.get(objective, 'pressure'))}"
    return say("pressure")


class AlertVoice(QObject):
    """Follows the dashboard and speaks on every rise. ``say`` does the speaking; spoken
    ``languages`` are those a voice is installed for (others fall back to English). Owned by
    the bridge, so it lives as long as the dashboard does."""

    def __init__(
        self,
        bridge: Any,
        say: Callable[[str], None],
        *,
        languages: Collection[str] = ("en", "hi"),
    ) -> None:
        super().__init__(bridge)
        self._bridge = bridge
        self._say = say
        self._languages = languages
        self._level = self._current_level()
        bridge.viewChanged.connect(self._on_view)

    def _current_level(self) -> Level:
        view: Mapping[str, Any] = self._bridge.property("view")
        return Level.parse(str(view.get("level", "quiet")))

    def _on_view(self) -> None:
        view: Mapping[str, Any] = self._bridge.property("view")
        level = self._current_level()
        previous, self._level = self._level, level
        if view.get("paused"):
            return
        language = str(self._bridge.property("language"))
        spoken: Language = "hi" if language == "hi" and "hi" in self._languages else "en"
        text = spoken_alert(previous, level, str(view.get("objectiveKey", "")), spoken)
        if text is not None:
            self._say(text)


class QtSpeaker:
    """Windows speech through Qt, preferring Indian-English and Hindi voices."""

    def __init__(self) -> None:
        from PySide6.QtTextToSpeech import QTextToSpeech

        engines = QTextToSpeech.availableEngines()
        self._tts = QTextToSpeech("winrt" if "winrt" in engines else "")
        # The engine lists only the current locale's voices: look at each locale in turn.
        by_locale = {}
        for locale in self._tts.availableLocales():
            self._tts.setLocale(locale)
            by_locale[locale.name()] = list(self._tts.availableVoices())
        self._hindi = [v for name, vs in by_locale.items() if name.startswith("hi") for v in vs]
        english = by_locale.get("en_IN") or by_locale.get("en_US") or []
        self._english = english[0] if english else None

    def voice_name(self) -> str:
        return self._english.name() if self._english is not None else ""

    @property
    def languages(self) -> tuple[str, ...]:
        return ("en", "hi") if self._hindi else ("en",)

    def say(self, text: str) -> None:
        is_hindi = any("ऀ" <= ch <= "ॿ" for ch in text)
        voice = self._hindi[0] if is_hindi and self._hindi else self._english
        if voice is not None:
            self._tts.setVoice(voice)
        self._tts.say(text)
