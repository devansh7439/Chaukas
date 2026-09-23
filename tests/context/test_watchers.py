"""Watchers turn OS observations into ContextEvents, each reported once."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from chaukas.context.downloads import DownloadClassifier, DownloadWatcher
from chaukas.context.processes import ProcessInfo, ProcessWatcher
from chaukas.context.rules import ContextRules
from chaukas.context.windows import WindowWatcher
from chaukas.core.clock import VirtualClock
from chaukas.core.models import ContextEvent, ContextKind

C = ContextKind


@pytest.fixture(scope="module")
def rules() -> ContextRules:
    return ContextRules.load()


def proc(pid: int, name: str, product: str = "") -> ProcessInfo:
    return ProcessInfo(pid=pid, name=name, exe=None, company="", product=product)


class TestProcessWatcher:
    def test_reports_a_remote_tool_once_when_it_starts(self, rules: ContextRules) -> None:
        snapshots = [
            [proc(1, "explorer.exe")],
            [proc(1, "explorer.exe"), proc(2, "AnyDesk.exe")],
            [proc(1, "explorer.exe"), proc(2, "AnyDesk.exe")],
        ]
        watcher = ProcessWatcher(rules, lambda: snapshots.pop(0))
        assert watcher.poll(1.0) == []
        (event,) = watcher.poll(2.0)
        assert event.kind is C.REMOTE_APP_STARTED
        assert event.t == 2.0
        assert event.detail == "AnyDesk.exe"
        assert watcher.poll(3.0) == []

    def test_tools_already_running_at_start_are_not_reported(self, rules: ContextRules) -> None:
        # AnyDesk left running from last week is not evidence about this call.
        snapshots = [[proc(7, "AnyDesk.exe")], [proc(7, "AnyDesk.exe")]]
        watcher = ProcessWatcher(rules, lambda: snapshots.pop(0))
        assert watcher.poll(0.0) == []
        assert watcher.poll(1.0) == []

    def test_a_restart_is_reported_again(self, rules: ContextRules) -> None:
        snapshots = [[], [proc(2, "TeamViewer.exe")], [], [proc(3, "TeamViewer.exe")]]
        watcher = ProcessWatcher(rules, lambda: snapshots.pop(0))
        results = [watcher.poll(float(t)) for t in range(4)]
        assert [len(r) for r in results] == [0, 1, 0, 1]

    def test_renamed_tools_are_caught_by_product_name(self, rules: ContextRules) -> None:
        snapshots = [[], [proc(9, "invoice_viewer.exe", product="AnyDesk")]]
        watcher = ProcessWatcher(rules, lambda: snapshots.pop(0))
        watcher.poll(0.0)
        (event,) = watcher.poll(1.0)
        assert event.detail == "invoice_viewer.exe (AnyDesk)"


class TestWindowWatcher:
    def test_window_changes_and_bank_pages(self, rules: ContextRules) -> None:
        watcher = WindowWatcher(rules)
        assert watcher.observe(1.0, 100, "Inbox - Gmail") == []  # first window: baseline
        events = watcher.observe(2.0, 200, "DemoBank (MOCK) - Login")
        assert [e.kind for e in events] == [C.WINDOW_CHANGED, C.BANK_PAGE]
        assert events[1].detail == "DemoBank (MOCK) - Login"
        assert watcher.observe(3.0, 200, "DemoBank (MOCK) - Login") == []  # nothing new

    def test_navigating_inside_one_window_is_seen_through_the_title(
        self, rules: ContextRules
    ) -> None:
        watcher = WindowWatcher(rules)
        watcher.observe(1.0, 200, "DemoBank (MOCK) - Login")
        events = watcher.observe(2.0, 200, "DemoBank (MOCK) - Transfer Funds")
        assert [e.kind for e in events] == [C.TRANSFER_PAGE]

    def test_no_foreground_window(self, rules: ContextRules) -> None:
        watcher = WindowWatcher(rules)
        assert watcher.observe(1.0, None, "") == []


class TestDownloadClassifier:
    def test_created_executable(self, rules: ContextRules) -> None:
        classifier = DownloadClassifier(rules)
        event = classifier.created(5.0, Path("C:/Users/a/Downloads/AnyDesk.exe"))
        assert event is not None
        assert event.kind is C.DOWNLOAD_EXECUTABLE
        assert event.detail == "AnyDesk.exe"

    def test_browser_rename_at_the_end_of_a_download(self, rules: ContextRules) -> None:
        classifier = DownloadClassifier(rules)
        partial = Path("C:/Users/a/Downloads/Unconfirmed 123.crdownload")
        assert classifier.created(5.0, partial) is None
        event = classifier.moved(9.0, partial, Path("C:/Users/a/Downloads/AnyDesk.exe"))
        assert event is not None
        assert event.t == 9.0

    def test_the_same_file_is_reported_once(self, rules: ContextRules) -> None:
        classifier = DownloadClassifier(rules)
        path = Path("C:/Users/a/Downloads/AnyDesk.exe")
        assert classifier.created(1.0, path) is not None
        assert classifier.moved(2.0, Path("x.tmp"), path) is None

    def test_other_files_are_ignored(self, rules: ContextRules) -> None:
        assert DownloadClassifier(rules).created(1.0, Path("C:/d/report.pdf")) is None


def test_the_real_folder_watcher_sees_a_finished_download(
    rules: ContextRules, tmp_path: Path
) -> None:
    pytest.importorskip("watchdog")
    seen: list[ContextEvent] = []
    arrived = threading.Event()

    def publish(event: ContextEvent) -> None:
        seen.append(event)
        arrived.set()

    watcher = DownloadWatcher(tmp_path, DownloadClassifier(rules), VirtualClock(7.0), publish)
    watcher.start()
    try:
        partial = tmp_path / "AnyDesk.exe.crdownload"
        partial.write_bytes(b"MZ")
        partial.rename(tmp_path / "AnyDesk.exe")  # what a browser does at the end
        assert arrived.wait(5.0)
    finally:
        watcher.stop()
    assert [(e.t, e.kind, e.detail) for e in seen] == [(7.0, C.DOWNLOAD_EXECUTABLE, "AnyDesk.exe")]
