"""The 1 Hz context monitor, event files for replay, and the real Windows readers."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from chaukas.context.monitor import ContextMonitor
from chaukas.context.processes import ProcessInfo, ProcessWatcher
from chaukas.context.replay_events import read_events, write_events
from chaukas.context.rules import ContextRules
from chaukas.context.windows import WindowWatcher
from chaukas.core.clock import VirtualClock
from chaukas.core.errors import ConfigError
from chaukas.core.models import ContextEvent, ContextKind

C = ContextKind
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


@pytest.fixture(scope="module")
def rules() -> ContextRules:
    return ContextRules.load()


class TestMonitor:
    def test_poll_once_merges_both_watchers(self, rules: ContextRules) -> None:
        snapshots: list[list[ProcessInfo]] = [
            [],
            [ProcessInfo(pid=4, name="AnyDesk.exe", exe=None, company="", product="")],
        ]
        titles = [(1, "Inbox"), (2, "DemoBank (MOCK) - Transfer Funds")]
        published: list[ContextEvent] = []
        clock = VirtualClock()
        monitor = ContextMonitor(
            clock=clock,
            publish=published.append,
            processes=ProcessWatcher(rules, lambda: snapshots.pop(0)),
            windows=WindowWatcher(rules),
            read_foreground=lambda: titles.pop(0),
            poll_s=1.0,
        )
        monitor.poll_once()
        clock.advance_to(1.0)
        monitor.poll_once()
        assert [(e.t, e.kind) for e in published] == [
            (1.0, C.REMOTE_APP_STARTED),
            (1.0, C.WINDOW_CHANGED),
            (1.0, C.TRANSFER_PAGE),
        ]

    def test_downloads_are_part_of_each_poll(self, rules: ContextRules, tmp_path: Path) -> None:
        from chaukas.context.downloads import DownloadClassifier, DownloadPoller

        published: list[ContextEvent] = []
        clock = VirtualClock()
        monitor = ContextMonitor(
            clock=clock,
            publish=published.append,
            processes=ProcessWatcher(rules, list),
            windows=WindowWatcher(rules),
            read_foreground=lambda: None,
            poll_s=1.0,
            downloads=DownloadPoller(tmp_path, DownloadClassifier(rules)),
        )
        monitor.poll_once()
        (tmp_path / "TeamViewer_Setup.exe").write_bytes(b"MZ")
        clock.advance_to(1.0)
        monitor.poll_once()
        assert [(e.t, e.kind) for e in published] == [(1.0, C.DOWNLOAD_EXECUTABLE)]

    def test_background_thread_starts_and_stops(self, rules: ContextRules) -> None:
        polled = threading.Event()

        def read_foreground() -> tuple[int, str]:
            polled.set()
            return (1, "Inbox")

        monitor = ContextMonitor(
            clock=VirtualClock(),
            publish=lambda event: None,
            processes=ProcessWatcher(rules, list),
            windows=WindowWatcher(rules),
            read_foreground=read_foreground,
            poll_s=0.01,
        )
        with monitor:
            assert polled.wait(2.0)
        assert not monitor.running

    def test_a_failing_reader_does_not_kill_the_monitor(self, rules: ContextRules) -> None:
        calls = {"n": 0}

        def flaky() -> list[ProcessInfo]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("access denied")
            return []

        monitor = ContextMonitor(
            clock=VirtualClock(),
            publish=lambda event: None,
            processes=ProcessWatcher(rules, flaky),
            windows=WindowWatcher(rules),
            read_foreground=lambda: None,
            poll_s=1.0,
        )
        monitor.poll_once()
        monitor.poll_once()
        assert calls["n"] == 2


class TestEventFiles:
    def test_round_trip(self, tmp_path: Path) -> None:
        events = [
            ContextEvent(t=52.0, kind=C.BANK_PAGE, detail="DemoBank (MOCK) - Login"),
            ContextEvent(t=71.5, kind=C.TRANSFER_PAGE, detail="DemoBank (MOCK) - Transfer Funds"),
        ]
        path = tmp_path / "DA01.jsonl"
        write_events(path, events)
        assert path.read_text(encoding="utf-8").splitlines()[0] == (
            '{"t": 52.0, "kind": "bank_page", "detail": "DemoBank (MOCK) - Login"}'
        )
        assert read_events(path) == events

    def test_events_come_back_in_time_order(self, tmp_path: Path) -> None:
        path = tmp_path / "x.jsonl"
        path.write_text(
            '{"t": 9, "kind": "bank_page"}\n\n{"t": 3, "kind": "remote_app_started"}\n',
            encoding="utf-8",
        )
        assert [e.t for e in read_events(path)] == [3.0, 9.0]

    @pytest.mark.parametrize("line", ['{"t": 1}', "not json", '{"t": -1, "kind": "bank_page"}'])
    def test_bad_lines_name_the_file_and_line(self, tmp_path: Path, line: str) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text(line + "\n", encoding="utf-8")
        with pytest.raises(ConfigError, match=r"bad\.jsonl:1"):
            read_events(path)


@windows_only
class TestWindowsReaders:
    def test_version_info_of_a_system_executable(self) -> None:
        from chaukas.context.win32 import file_version_strings

        strings = file_version_strings(Path(sys.executable))
        assert strings.get("ProductName")  # python.exe carries version info

    def test_version_info_of_a_non_executable_is_empty(self, tmp_path: Path) -> None:
        from chaukas.context.win32 import file_version_strings

        plain = tmp_path / "plain.txt"
        plain.write_text("hi", encoding="utf-8")
        assert file_version_strings(plain) == {}

    def test_downloads_folder_resolves(self) -> None:
        from chaukas.context.win32 import downloads_folder

        assert downloads_folder().is_absolute()

    def test_foreground_window_does_not_raise(self) -> None:
        from chaukas.context.win32 import foreground_window

        result = foreground_window()
        assert result is None or isinstance(result[1], str)

    def test_listing_processes_finds_this_one(self) -> None:
        pytest.importorskip("psutil")
        import os

        from chaukas.context.processes import list_processes

        assert any(p.pid == os.getpid() for p in list_processes())
