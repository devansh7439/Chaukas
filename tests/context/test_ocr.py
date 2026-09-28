"""Triggered OCR of the active window: only while a call is suspicious, never stored."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable

import pytest

from chaukas.context.ocr import TriggeredOcr, WindowImage
from chaukas.context.rules import ContextRules
from chaukas.core.models import ContextKind

RULES = ContextRules.load()


def needs_windows_ocr() -> None:
    """Skip unless the OCR bindings are installed, loading Qt's C++ runtime first: winrt
    bundles an older msvcp140.dll, and if it loads first any later Qt import crashes."""
    import contextlib

    with contextlib.suppress(ImportError):
        import PySide6.QtCore  # noqa: F401
    pytest.importorskip("winrt.windows.media.ocr")


def image(title: str = "Secure verification", handle: int = 7) -> WindowImage:
    return WindowImage(handle=handle, title=title, width=10, height=10, bgra=b"\0" * 400)


class FakeReader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.reads = 0

    def read(self, window: WindowImage) -> str:
        self.reads += 1
        return self.text


def ocr(reader: FakeReader, *, suspicious: list[bool], window: WindowImage | None = None,
        interval_s: float = 3.0) -> TriggeredOcr:  # fmt: skip
    return TriggeredOcr(RULES, should_read=lambda: suspicious[0],
                        capture=lambda: window or image(), reader=reader,
                        interval_s=interval_s, synchronous=True)  # fmt: skip


class TestTrigger:
    def test_nothing_is_read_while_the_call_is_calm(self) -> None:
        reader = FakeReader("Enter OTP")
        assert ocr(reader, suspicious=[False]).poll(10.0) == []
        assert reader.reads == 0

    def test_an_otp_box_is_reported_once_the_call_is_suspicious(self) -> None:
        (event,) = ocr(FakeReader("Please enter the OTP sent to your mobile"),
                       suspicious=[True]).poll(10.0)  # fmt: skip
        assert event.kind is ContextKind.OTP_FIELD_VISIBLE
        assert event.t == 10.0
        assert "Secure verification" in event.detail

    def test_reads_are_rate_limited(self) -> None:
        reader = FakeReader("nothing interesting")
        watcher = ocr(reader, suspicious=[True], interval_s=3.0)
        for t in (10.0, 11.0, 12.0, 13.5):
            watcher.poll(t)
        assert reader.reads == 2  # at 10.0 and 13.5

    def test_the_same_page_is_reported_only_once(self) -> None:
        watcher = ocr(FakeReader("Enter OTP"), suspicious=[True], interval_s=0.0)
        assert len(watcher.poll(1.0)) == 1
        assert watcher.poll(2.0) == []

    def test_chaukas_never_reads_its_own_window(self) -> None:
        reader = FakeReader("Enter OTP")
        own = WindowImage(handle=7, title="Chaukas", width=10, height=10, bgra=b"\0" * 400,
                          pid=os.getpid())  # fmt: skip
        watcher = ocr(reader, suspicious=[True], window=own)
        assert watcher.poll(1.0) == []
        assert reader.reads == 0

    def test_a_transfer_form_needs_two_transfer_words(self) -> None:
        assert ocr(FakeReader("Amount"), suspicious=[True]).poll(1.0) == []
        (event,) = ocr(FakeReader("Beneficiary name  Amount ₹"), suspicious=[True]).poll(1.0)
        assert event.kind is ContextKind.TRANSFER_PAGE

    def test_session_end_forgets_what_was_reported(self) -> None:
        watcher = ocr(FakeReader("Enter OTP"), suspicious=[True], interval_s=0.0)
        watcher.poll(1.0)
        watcher.reset()
        assert len(watcher.poll(2.0)) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR")
class TestWindowsOcr:
    def test_reads_text_from_real_pixels(self) -> None:
        pytest.importorskip("PySide6")  # before winrt: see test_ocr_then_qt_does_not_crash
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont, QImage, QPainter

        from chaukas.ui.app import create_app

        create_app(headless=True)  # headless Qt only has fonts if pointed at the bundled ones
        needs_windows_ocr()
        from chaukas.context.ocr import WindowsOcr

        canvas = QImage(640, 160, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.white)
        painter = QPainter(canvas)
        painter.setFont(QFont("Plus Jakarta Sans", 36))
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(20, 100, "Enter OTP 482913")
        painter.end()
        pixels = bytes(canvas.constBits())[: canvas.width() * canvas.height() * 4]
        try:
            text = WindowsOcr().read(WindowImage(handle=1, title="t", width=canvas.width(),
                                                 height=canvas.height(), bgra=pixels))  # fmt: skip
        except RuntimeError as exc:
            pytest.skip(str(exc))  # no OCR language installed
        assert "OTP" in text
        assert RULES.classify_screen_text(text) is ContextKind.OTP_FIELD_VISIBLE

    def test_captures_the_foreground_window_or_nothing(self) -> None:
        pytest.importorskip("mss")
        from chaukas.context.ocr import capture_active_window

        shot = capture_active_window()
        if shot is not None:
            assert len(shot.bgra) == shot.width * shot.height * 4
            assert shot.pid > 0  # the owner process is known, so our own windows are skipped

    def test_ocr_then_qt_does_not_crash(self) -> None:
        # winrt ships an older msvcp140.dll: if it loads before Qt's, importing Qt crashes
        # the process. WindowsOcr loads Qt's runtime first. In a fresh process, because the
        # dangerous order can only be tested before anything else loaded Qt.
        needs_windows_ocr()
        pytest.importorskip("PySide6")
        import subprocess

        script = (
            "from chaukas.context.ocr import WindowImage, WindowsOcr\n"
            "try:\n"
            "    WindowsOcr().read(WindowImage(1, 't', 64, 64, bytes(64 * 64 * 4)))\n"
            "except RuntimeError:\n"
            "    pass\n"
            "from PySide6.QtGui import QGuiApplication\n"
            "print('alive')\n"
        )
        done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                              timeout=120)  # fmt: skip
        assert done.returncode == 0, done.stderr[-500:]
        assert "alive" in done.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR")
class TestAvailability:
    """Windows.Media.Ocr needs no package identity (the Windows App SDK TextRecognizer does);
    what can differ between PCs is whether an OCR language or the bindings are installed."""

    def test_this_test_process_has_no_package_identity(self) -> None:
        import ctypes

        length = ctypes.c_uint(0)
        no_package = 15700  # APPMODEL_ERROR_NO_PACKAGE
        assert ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) == (
            no_package
        )  # so the real-pixel OCR test above ran unpackaged

    def test_status_says_on_and_names_the_language(self) -> None:
        needs_windows_ocr()
        from chaukas.context.ocr import ocr_status

        available, description = ocr_status()
        if not available and "language" in description:
            pytest.skip(description)  # a PC without an OCR language
        assert available
        assert description.startswith("on (")

    def test_status_explains_missing_bindings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from chaukas.context.ocr import ocr_status

        monkeypatch.setitem(sys.modules, "winrt.windows.media.ocr", None)
        available, description = ocr_status()
        assert not available
        assert "not installed" in description


class SlowReader(FakeReader):
    def __init__(self, text: str, seconds: float) -> None:
        super().__init__(text)
        self.seconds = seconds

    def read(self, window: WindowImage) -> str:
        import time

        time.sleep(self.seconds)
        return super().read(window)


class TestNeverBlocksTheMonitor:
    """OCR runs on its own worker: process, window and Downloads polling never wait for it."""

    def _watcher(self, reader: FakeReader) -> TriggeredOcr:
        return TriggeredOcr(RULES, should_read=lambda: True, capture=image, reader=reader,
                            interval_s=0.0, synchronous=False)  # fmt: skip

    def test_poll_returns_at_once_and_the_result_arrives_on_a_later_poll(self) -> None:
        import time

        watcher = self._watcher(SlowReader("Enter OTP", 0.5))
        start = time.perf_counter()
        assert watcher.poll(10.0) == []
        assert time.perf_counter() - start < 0.2  # did not wait for the 0.5 s read
        events: list = []
        deadline = time.perf_counter() + 5.0
        while not events and time.perf_counter() < deadline:
            time.sleep(0.05)
            events = watcher.poll(11.0)
        (event,) = events
        assert event.kind is ContextKind.OTP_FIELD_VISIBLE
        assert event.t == 10.0  # when the screen was looked at, not when OCR finished
        watcher.close()

    def test_only_one_read_at_a_time(self) -> None:
        import time

        reader = SlowReader("nothing", 0.3)
        watcher = self._watcher(reader)
        for t in range(5):
            watcher.poll(float(t))
        time.sleep(0.6)
        watcher.poll(10.0)
        watcher.close()
        assert reader.reads <= 2

    def test_a_result_from_before_the_session_ended_is_dropped(self) -> None:
        import time

        watcher = self._watcher(SlowReader("Enter OTP", 0.3))
        watcher.poll(1.0)
        watcher.reset()  # the session ends while the read is in flight
        time.sleep(0.5)
        assert all(e.t != 1.0 for e in watcher.poll(2.0))
        watcher.close()


class TestHardening:
    """Red-team regressions: spoofed titles, hung OCR, malformed output, window switches."""

    def test_a_page_titled_chaukas_in_another_process_is_still_read(self) -> None:
        # A phishing page can call itself "Chaukas"; only our own process is skipped.
        spoof = WindowImage(handle=9, title="Chaukas - verify your OTP", width=10, height=10,
                            bgra=b"\0" * 400, pid=os.getpid() + 1)  # fmt: skip
        (event,) = ocr(FakeReader("Enter OTP"), suspicious=[True], window=spoof).poll(1.0)
        assert event.kind is ContextKind.OTP_FIELD_VISIBLE

    def test_our_own_process_is_never_read_whatever_its_title(self) -> None:
        reader = FakeReader("Enter OTP")
        own = WindowImage(handle=9, title="Dashboard", width=10, height=10, bgra=b"\0" * 400,
                          pid=os.getpid())  # fmt: skip
        assert ocr(reader, suspicious=[True], window=own).poll(1.0) == []
        assert reader.reads == 0

    @pytest.mark.parametrize("bad", [None, 42, b"Enter OTP"])
    def test_malformed_reader_output_is_ignored(self, bad: object) -> None:
        reader = FakeReader("")
        reader.text = bad  # type: ignore[assignment]
        assert ocr(reader, suspicious=[True]).poll(1.0) == []

    def test_huge_text_is_capped_and_classified_quickly(self) -> None:
        import time

        start = time.perf_counter()
        (event,) = ocr(FakeReader("Enter OTP " + "x " * 3_000_000),
                       suspicious=[True]).poll(1.0)  # fmt: skip
        assert event.kind is ContextKind.OTP_FIELD_VISIBLE
        assert time.perf_counter() - start < 1.0

    def test_the_event_names_the_window_that_was_captured(self) -> None:
        windows = iter([image(title="MyBank - Verify", handle=1), image(title="Notepad", handle=2)])
        watcher = TriggeredOcr(RULES, should_read=lambda: True, capture=lambda: next(windows),
                               reader=FakeReader("Enter OTP"), interval_s=0.0,
                               synchronous=True)  # fmt: skip
        (event,) = watcher.poll(1.0)
        assert "MyBank - Verify" in event.detail


class StuckReader(FakeReader):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.release = threading.Event()

    def read(self, window: WindowImage) -> str:
        self.reads += 1
        self.release.wait(10.0)
        return str(self.text)


class TestTimeouts:
    def _watcher(self, reader: FakeReader, timeout_s: float = 2.0) -> TriggeredOcr:
        return TriggeredOcr(RULES, should_read=lambda: True, capture=image, reader=reader,
                            interval_s=0.0, timeout_s=timeout_s)  # fmt: skip

    @staticmethod
    def _wait_for(condition: Callable[[], bool]) -> None:
        import time

        deadline = time.perf_counter() + 5.0
        while not condition() and time.perf_counter() < deadline:
            time.sleep(0.02)

    def test_a_hung_read_is_abandoned_and_reading_resumes(self) -> None:
        reader = StuckReader("Enter OTP")
        watcher = self._watcher(reader)
        watcher.poll(0.0)
        self._wait_for(lambda: reader.reads == 1)
        watcher.poll(1.0)  # still within the timeout: no second read
        assert reader.reads == 1
        watcher.poll(3.0)  # past it: the hung read is abandoned, a new one starts
        self._wait_for(lambda: reader.reads == 2)
        assert (reader.reads, watcher.timeouts) == (2, 1)
        reader.release.set()
        watcher.close()

    def test_gives_up_after_repeated_hangs_and_says_why(self) -> None:
        reader = StuckReader("Enter OTP")
        watcher = self._watcher(reader, timeout_s=1.0)
        for t in range(0, 20, 2):
            watcher.poll(float(t))
            self._wait_for(lambda: reader.reads >= min(3, t // 2 + 1))
        assert watcher.timeouts == 3
        assert reader.reads == 3  # no further read is started
        assert watcher.disabled is not None and "stopped responding" in watcher.disabled
        reader.release.set()
        watcher.close()
