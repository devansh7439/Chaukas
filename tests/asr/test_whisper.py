"""Speech-to-text on the CPU with faster-whisper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("faster_whisper")

from chaukas.asr.whisper_cpu import ModelMissingError, WhisperCpu  # noqa: E402


@dataclass
class _Segment:
    text: str
    no_speech_prob: float


@dataclass
class _Info:
    language: str


class FakeModel:
    """Answers like faster-whisper's WhisperModel; records the language it was asked for."""

    def __init__(self, answers: dict[str | None, tuple[str, list[tuple[str, float]]]]) -> None:
        self.answers = answers
        self.asked: list[str | None] = []

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[list[_Segment], _Info]:
        language = kwargs["language"]
        self.asked.append(language)
        self.kwargs = kwargs
        detected, segments = self.answers[language]
        return [_Segment(t, p) for t, p in segments], _Info(detected)


def wrapped(model: FakeModel, language: str = "auto") -> WhisperCpu:
    return WhisperCpu.from_model(model, language=language, beam_size=1, no_speech_threshold=0.6)


SILENCE = np.zeros(16_000, dtype=np.float32)


class TestWrapper:
    def test_joins_segments_and_reports_language_and_time(self) -> None:
        model = FakeModel({None: ("en", [("Hello.", 0.1), (" Tell me the OTP.", 0.05)])})
        transcript = wrapped(model).transcribe(SILENCE)
        assert transcript.text == "Hello. Tell me the OTP."
        assert transcript.language == "en"
        assert transcript.ms >= 0

    def test_hallucinations_on_silence_are_dropped(self) -> None:
        model = FakeModel({None: ("en", [("Thank you.", 0.92)])})
        assert wrapped(model).transcribe(SILENCE).text == ""

    def test_hindi_mistaken_for_urdu_is_transcribed_again_as_hindi(self) -> None:
        model = FakeModel({None: ("ur", [("آپ کا او ٹی پی", 0.1)]),
                           "hi": ("hi", [("आपका ओटीपी बताओ", 0.1)])})  # fmt: skip
        transcript = wrapped(model).transcribe(SILENCE)
        assert model.asked == [None, "hi"]
        assert transcript.text == "आपका ओटीपी बताओ"
        assert transcript.language == "hi"

    def test_a_fixed_language_is_passed_through(self) -> None:
        model = FakeModel({"en": ("en", [("OTP batao", 0.1)])})
        wrapped(model, language="en").transcribe(SILENCE)
        assert model.asked == ["en"]

    def test_a_model_that_is_not_downloaded_is_a_clear_error(self) -> None:
        with pytest.raises(ModelMissingError, match="chaukas setup"):
            WhisperCpu("tiny.en", language="auto", cpu_threads=1, beam_size=1,
                       no_speech_threshold=0.6)  # fmt: skip


def test_real_speech_is_transcribed(speech: Callable[[str], object]) -> None:
    try:
        whisper = WhisperCpu("base", language="auto", cpu_threads=4, beam_size=1,
                             no_speech_threshold=0.6)  # fmt: skip
    except ModelMissingError:
        pytest.skip("Whisper base is not downloaded")
    transcript = whisper.transcribe(speech("I am calling from the bank. Please tell me the OTP."))
    assert "otp" in transcript.text.lower()
    assert transcript.language == "en"
    assert whisper.transcribe(np.zeros(16_000, dtype=np.float32)).text == ""


class TestLanguageHint:
    def test_a_hint_skips_detection(self) -> None:
        model = FakeModel({"hi": ("hi", [("OTP batao", 0.1)])})
        transcript = wrapped(model).transcribe(SILENCE, language="hi")
        assert model.asked == ["hi"]
        assert transcript.language == "hi"

    def test_a_configured_language_wins_over_a_hint(self) -> None:
        model = FakeModel({"en": ("en", [("OTP batao", 0.1)])})
        wrapped(model, language="en").transcribe(SILENCE, language="hi")
        assert model.asked == ["en"]


def test_hotwords_reach_whisper_only_when_set() -> None:
    model = FakeModel({None: ("en", [("Install AnyDesk", 0.1)])})
    WhisperCpu.from_model(model, language="auto", beam_size=1, no_speech_threshold=0.6,
                          hotwords="OTP, AnyDesk").transcribe(SILENCE)  # fmt: skip
    assert model.kwargs["hotwords"] == "OTP, AnyDesk"
    wrapped(model).transcribe(SILENCE)
    assert model.kwargs["hotwords"] is None
