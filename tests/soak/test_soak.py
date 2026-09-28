"""Soak: hours of speech and screen events through the live session, as the app runs it.

Loopback hears all PC audio and a session only ends after 30 minutes of silence, so one
session can last all day. Whatever grows per line or per tick must be bounded, and the
cost of a tick must not grow with the length of the session.
"""

from __future__ import annotations

import time
import tracemalloc

from chaukas.core.config import load_config
from chaukas.core.models import ContextEvent, ContextKind, HeardLine, Stream
from chaukas.engine.templates import load_templates
from chaukas.signals.lexicon import Lexicon
from chaukas.ui.live import LiveSession, ScoreHistory

LINES = (
    "Good evening, today we discuss the weather and the cricket match.",
    "The police arrested a suspect after the CBI raid, the anchor said.",
    "Please stay on the line, your call is important to us.",
    "Aaj ka mausam saaf rahega, baarish ki sambhavana kam hai.",
    "Share your screen so the whole team can see the slides.",
    "Kisi ko mat batana, yeh surprise party hai.",
)
LINE_EVERY_S = 4.0
HOUR = 3600.0


def talk(session: LiveSession, start: float, end: float) -> None:
    """Speech every few seconds and a screen event every minute, ticking once a second."""
    t = start
    n = int(start / LINE_EVERY_S)
    while t < end:
        text = LINES[n % len(LINES)]
        session.hear(HeardLine(stream=Stream.CALLER, t_start=t, t_end=t + 3.0, text=text))
        if n % 15 == 0:
            session.observe(ContextEvent(t=t, kind=ContextKind.BANK_PAGE, detail="MyBank"))
        for tick in range(int(LINE_EVERY_S)):
            session.advance(t + tick + 1.0)
        t += LINE_EVERY_S
        n += 1


def ticks_per_second(session: LiveSession, start: float) -> float:
    began = time.perf_counter()
    talk(session, start, start + 240.0)
    return 240.0 / (time.perf_counter() - began)


def test_six_hours_of_speech_keep_memory_and_tick_cost_flat() -> None:
    session = LiveSession(load_config(), Lexicon.load(), load_templates())
    talk(session, 0.0, HOUR)  # warm up: every cache and window is at its working size
    early_speed = ticks_per_second(session, HOUR)

    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    talk(session, HOUR + 240.0, 6 * HOUR)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    grown = sum(stat.size_diff for stat in after.compare_to(before, "filename"))
    late_speed = ticks_per_second(session, 6 * HOUR)

    assert grown < 2_000_000, f"memory grew by {grown / 1e6:.1f} MB over five hours"
    assert late_speed > early_speed / 2, (early_speed, late_speed)
    assert len(session.history) <= ScoreHistory.MAX_POINTS
    assert len(session.transcript) < 500  # the privacy horizon still applies
