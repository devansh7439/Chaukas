"""The live session behind the dashboard. Pure Python, no Qt.

Owns the signal extractor and risk engine (through ``Session``) and advances them in real
time. Input comes from a case script played on the clock (demo mode), from lines typed
into the dashboard, and later from the live audio pipeline. It also keeps what the screen
needs: the call log and the risk history.

Pausing drops everything Chaukas would have heard or seen, exactly as if it were not
listening. Ending the session wipes the transcript, the history and the engine's state.

Privacy (blueprint 6.9): transcript lines older than ``privacy.transcript_horizon_s`` are
dropped from memory, and ``privacy.session_idle_end_s`` without speech ends the session.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from chaukas.core.config import ChaukasConfig
from chaukas.core.models import (
    ContextEvent,
    HeardLine,
    LLMAssessment,
    RiskState,
    Segment,
    Stream,
)
from chaukas.core.timeline import Timeline
from chaukas.engine.risk import RiskEngine
from chaukas.engine.templates import ChainTemplate
from chaukas.evaluation.cases import AssessmentCue, Case, ContextCue, SpeechLine
from chaukas.evaluation.session import Session, Snapshot
from chaukas.signals.extractor import SignalExtractor
from chaukas.signals.lexicon import Lexicon

Speaker = Literal["caller", "user", "system"]

WORDS_PER_SECOND: Final = 2.5
MIN_LINE_S: Final = 0.6

_Scheduled = SpeechLine | ContextCue | AssessmentCue


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    t: float
    speaker: Speaker
    text: str  # for system entries: the context detail
    kinds: tuple[str, ...]  # signal kinds from this line, or the context kind


class LiveSession:
    def __init__(
        self,
        config: ChaukasConfig,
        lexicon: Lexicon,
        templates: Sequence[ChainTemplate],
        *,
        case: Case | None = None,
        tick_s: float = 1.0,
    ) -> None:
        self._session = Session(
            SignalExtractor(lexicon, config.signals),
            RiskEngine.from_config(config, templates),
            tick_s=tick_s,
            session_id=case.case_id if case else "live",
        )
        self._paused = False
        self._horizon_s = config.privacy.transcript_horizon_s
        self._idle_end_s = config.privacy.session_idle_end_s
        self._last_speech: float | None = None
        self._transcript: list[TranscriptEntry] = []
        self._history: list[tuple[float, float]] = []
        self._scheduled: Timeline[_Scheduled] = Timeline()
        if case is not None:
            for line in case.lines:
                self._scheduled.push(line.t_end, line)
            for cue in case.cues:
                self._scheduled.push(cue.t, cue)
            for verdict in case.assessments:
                self._scheduled.push(verdict.t, verdict)

    @property
    def now(self) -> float:
        return self._session.now

    @property
    def state(self) -> RiskState:
        return self._session.state

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def transcript(self) -> tuple[TranscriptEntry, ...]:
        return tuple(self._transcript)

    @property
    def history(self) -> list[tuple[float, float]]:
        return list(self._history)

    def advance(self, now: float) -> bool:
        """Process everything due by ``now`` and evaluate up to it. True if the session just
        ended because nobody had spoken for ``session_idle_end_s``."""
        while (due := self._scheduled.peek_time()) is not None and due <= now:
            _, item = self._scheduled.pop()
            if not self._paused:
                self._handle(item)
        self._record(self._session.advance_to(now))
        if self._session.now < now:
            self._record([self._session.evaluate(now)])
        cutoff = now - self._horizon_s
        if self._transcript and self._transcript[0].t < cutoff:
            self._transcript = [entry for entry in self._transcript if entry.t >= cutoff]
        if self._last_speech is not None and now - self._last_speech >= self._idle_end_s:
            self.end_session()
            return True
        return False

    def hear(self, line: HeardLine) -> bool:
        """A line transcribed from live audio. False if ignored (paused, or empty)."""
        if self._paused or not line.text.strip():
            return False
        duration = max(MIN_LINE_S, line.t_end - line.t_start)
        self._feed_line(SpeechLine(t=line.t_start, duration=duration, stream=line.stream,
                                   text=line.text.strip()))  # fmt: skip
        return True

    def observe(self, event: ContextEvent) -> None:
        """Something the desktop monitor saw."""
        if not self._paused:
            self._handle(ContextCue(t=event.t, kind=event.kind, detail=event.detail))

    def say(self, text: str, speaker: Stream) -> bool:
        """A line typed into the dashboard, as if just spoken. False if ignored."""
        text = text.strip()
        if not text or self._paused:
            return False
        # It was "spoken" just now: it ends now and lasted as long as it takes to say.
        spoken_for = max(MIN_LINE_S, len(text.split()) / WORDS_PER_SECOND)
        start = max(0.0, self._session.now - spoken_for)
        duration = max(MIN_LINE_S, self._session.now - start)
        self._feed_line(SpeechLine(t=start, duration=duration, stream=speaker, text=text))
        return True

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def dismiss(self) -> None:
        self._record(self._session.dismiss())

    def end_session(self) -> None:
        """Discard everything heard so far, and the rest of a demo script."""
        self._session.reset()
        self._transcript.clear()
        self._history.clear()
        self._last_speech = None
        self._scheduled = Timeline()
        self._record(self._session.advance_to(self._session.now))

    def _handle(self, item: _Scheduled) -> None:
        if isinstance(item, SpeechLine):
            self._feed_line(item)
        elif isinstance(item, ContextCue):
            event = ContextEvent(t=item.t, kind=item.kind, detail=item.detail)
            self._record(self._session.feed_context(event))
            if event.objective is not None:
                entry = TranscriptEntry(
                    t=item.t, speaker="system", text=item.detail, kinds=(item.kind.value,)
                )
                self._transcript.append(entry)
        else:
            verdict = LLMAssessment(
                t=item.t,
                addressed_to_user=item.addressed_to_user,
                suspected_objective=item.objective,
            )
            self._record(self._session.feed_assessment(verdict))

    def _feed_line(self, line: SpeechLine) -> None:
        segment = Segment(
            session_id=self._session.session_id,
            seg_id=self._session.next_segment_id(),
            stream=line.stream,
            t_start=line.t,
            t_end=line.t_end,
            text=line.text,
        )
        self._record(self._session.feed_segment(segment))
        self._last_speech = max(self._last_speech or 0.0, line.t_end)
        self._transcript.append(
            TranscriptEntry(
                t=line.t,
                speaker="caller" if line.stream is Stream.CALLER else "user",
                text=line.text,
                kinds=tuple(signal.kind.value for signal in self._session.last_signals),
            )
        )

    def _record(self, snapshots: list[Snapshot]) -> None:
        self._history.extend((snapshot.t, snapshot.state.score) for snapshot in snapshots)
