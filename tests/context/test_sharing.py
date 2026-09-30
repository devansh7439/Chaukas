"""Is the screen being shared? Windows records which apps capture the screen right now.

A browser meeting tab ("join the Meet link and share your screen") starts no remote tool,
but Chrome's capture shows up in the same per-app privacy records as the microphone.
"""

from __future__ import annotations

import sys

import pytest

from chaukas.context.rules import ContextRules
from chaukas.context.sharing import ScreenShareWatcher, read_capture_records
from chaukas.core.models import ContextKind

RULES = ContextRules.load()
CHROME = r"C:#Program Files#Google#Chrome#Application#chrome.exe"
OWN = r"C:\Users\me\AppData\Roaming\uv\python\cpython-3.12\python.exe"


class Records:
    """A changing set of capture records, as Windows would show them poll after poll."""

    def __init__(self, **initial: tuple[int, int]) -> None:
        self.now: dict[str, tuple[int, int]] | None = dict(initial)
        self.fail = False

    def __call__(self) -> dict[str, tuple[int, int]] | None:
        if self.fail:
            raise OSError("access denied")
        return self.now


def watcher(records: Records, exclude: tuple[str, ...] = ()) -> ScreenShareWatcher:
    return ScreenShareWatcher(RULES, read=records, exclude=exclude)


class TestWatcher:
    def test_a_share_that_starts_during_protection_is_reported(self) -> None:
        records = Records()
        sharing = watcher(records)
        assert sharing.poll(1.0) == []  # the first poll is the baseline
        records.now = {CHROME: (100, 0)}  # a stop time of 0: capturing now
        (event,) = sharing.poll(2.0)
        assert event.kind is ContextKind.SCREEN_SHARED
        assert event.t == 2.0
        assert event.detail == "chrome.exe"

    def test_it_is_reported_once_per_share(self) -> None:
        records = Records()
        sharing = watcher(records)
        sharing.poll(1.0)
        records.now = {CHROME: (100, 0)}
        assert len(sharing.poll(2.0)) == 1
        assert sharing.poll(3.0) == []

    def test_a_new_share_by_the_same_app_is_reported_again(self) -> None:
        records = Records()
        sharing = watcher(records)
        sharing.poll(1.0)
        records.now = {CHROME: (100, 0)}
        sharing.poll(2.0)
        records.now = {CHROME: (100, 150)}  # stopped
        assert sharing.poll(3.0) == []
        records.now = {CHROME: (200, 0)}  # "share your screen again"
        assert len(sharing.poll(4.0)) == 1

    def test_a_share_already_running_when_protection_starts_is_not_news(self) -> None:
        # Like remote tools already running before the call: presenting in a meeting.
        records = Records(**{CHROME: (100, 0)})
        sharing = watcher(records)
        assert sharing.poll(1.0) == []
        assert sharing.poll(2.0) == []

    def test_a_finished_share_is_not_a_share(self) -> None:
        records = Records()
        sharing = watcher(records)
        sharing.poll(1.0)
        records.now = {CHROME: (100, 150)}
        assert sharing.poll(2.0) == []

    def test_a_screenshot_tool_is_not_a_shared_screen(self) -> None:
        records = Records()
        sharing = watcher(records)
        sharing.poll(1.0)
        records.now = {"Microsoft.ScreenSketch_8wekyb3d8bbwe": (100, 0),
                       r"C:#Windows#System32#SnippingTool.exe": (100, 0)}  # fmt: skip
        assert sharing.poll(2.0) == []

    def test_chaukas_itself_is_excluded(self) -> None:
        records = Records()
        sharing = watcher(records, exclude=(OWN.upper(),))
        sharing.poll(1.0)
        records.now = {OWN.replace("\\", "#"): (100, 0)}
        assert sharing.poll(2.0) == []

    def test_a_store_app_is_named_by_its_package(self) -> None:
        records = Records()
        sharing = watcher(records)
        sharing.poll(1.0)
        records.now = {"MSTeams_8wekyb3d8bbwe": (100, 0)}
        (event,) = sharing.poll(2.0)
        assert event.detail == "MSTeams"

    def test_unreadable_records_change_nothing(self) -> None:
        records = Records()
        sharing = watcher(records)
        sharing.poll(1.0)
        records.fail = True
        assert sharing.poll(2.0) == []
        records.now = None  # no records at all (not Windows)
        records.fail = False
        assert sharing.poll(3.0) == []

    def test_a_share_is_not_missed_because_the_baseline_read_failed(self) -> None:
        records = Records()
        records.fail = True
        sharing = watcher(records)
        assert sharing.poll(1.0) == []
        records.fail = False
        records.now = {}
        assert sharing.poll(2.0) == []  # the first good read is the baseline
        records.now = {CHROME: (100, 0)}
        assert len(sharing.poll(3.0)) == 1

    def test_reset_takes_a_fresh_baseline(self) -> None:
        records = Records()
        sharing = watcher(records)
        sharing.poll(1.0)
        records.now = {CHROME: (100, 0)}
        sharing.poll(2.0)
        sharing.reset()
        assert sharing.poll(3.0) == []  # still sharing: now part of the new baseline


@pytest.mark.skipif(sys.platform != "win32", reason="Windows privacy records")
def test_the_real_records_can_be_read() -> None:
    records = read_capture_records()
    if records is None:
        pytest.skip("no app has captured the screen on this machine (e.g. a fresh CI server)")
    assert all(isinstance(start, int) and isinstance(stop, int)
               for start, stop in records.values())  # fmt: skip
