"""Triggered OCR of the active window: only while a call is suspicious, never stored."""

from __future__ import annotations

import sys

import pytest

from chaukas.context.ocr import TriggeredOcr, WindowImage
from chaukas.context.rules import ContextRules
from chaukas.core.models import ContextKind

RULES = ContextRules.load()


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
                        interval_s=interval_s)  # fmt: skip


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
        watcher = ocr(reader, suspicious=[True], window=image(title="Chaukas"))
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
        pytest.importorskip("winrt.windows.media.ocr")
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

    def test_ocr_then_qt_does_not_crash(self) -> None:
        # winrt ships an older msvcp140.dll: if it loads before Qt's, importing Qt crashes
        # the process. WindowsOcr loads Qt's runtime first. In a fresh process, because the
        # dangerous order can only be tested before anything else loaded Qt.
        pytest.importorskip("winrt.windows.media.ocr")
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
