"""Triggered OCR of the active window (blueprint 6.5): screen text, only when it matters.

Window titles miss what is inside a page: a generic title over an "Enter OTP" box. So when
a call is already suspicious (the alert level is notice or higher), the monitor reads the
text of the active window, at most once every ``interval_s``, and classifies it with the
same screen-text rules (OTP field, password field, transfer form). Nothing is read while a
call is calm.

Privacy: only the active window is captured; the image and the recognised text stay in
memory for the length of one classification, are never written anywhere and never logged.
Chaukas's own window is never read.

The OCR engine is Windows' built-in one (``Windows.Media.Ocr``): no model to download, on
the device, on x64 and ARM64, in every language pack the user has installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from chaukas.context.rules import ContextRules
from chaukas.core.models import ContextEvent, ContextKind

logger = logging.getLogger(__name__)

OWN_TITLE = "Chaukas"


@dataclass(frozen=True, slots=True)
class WindowImage:
    """The active window's pixels, top-down BGRA."""

    handle: int
    title: str
    width: int
    height: int
    bgra: bytes


class TextReader(Protocol):
    def read(self, image: WindowImage) -> str: ...


Capture = Callable[[], WindowImage | None]


_Seen = tuple[int, str, ContextKind]  # window handle, title, what its text shows


class TriggeredOcr:
    """Reads the active window's text while ``should_read()`` says the call is suspicious.

    Capture, OCR and classification run on one worker thread (about 130 ms for a full-screen
    window), so ``poll`` never waits: it starts a read when one is due and picks up the
    result on a later poll, timed when the screen was looked at. At most one read runs at a
    time, and a read still running when the session ends is discarded. ``synchronous=True``
    reads inside ``poll`` (tests).
    """

    __slots__ = ("_capture", "_executor", "_interval", "_last_read", "_pending", "_reader",
                 "_reported", "_rules", "_should_read")  # fmt: skip

    def __init__(
        self,
        rules: ContextRules,
        *,
        should_read: Callable[[], bool],
        capture: Capture,
        reader: TextReader,
        interval_s: float,
        synchronous: bool = False,
    ) -> None:
        self._rules = rules
        self._should_read = should_read
        self._capture = capture
        self._reader = reader
        self._interval = interval_s
        self._last_read: float | None = None
        self._reported: set[_Seen] = set()
        self._executor = None if synchronous else ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="chaukas-ocr")  # fmt: skip
        self._pending: tuple[Future[_Seen | None], float] | None = None

    def poll(self, now: float) -> list[ContextEvent]:
        events = self._collect()
        due = self._last_read is None or now - self._last_read >= self._interval
        if self._pending is None and due and self._should_read():
            self._last_read = now
            if self._executor is None:
                events.extend(self._report(self._look(), now))
            else:
                self._pending = (self._executor.submit(self._look), now)
        return events

    def reset(self) -> None:
        """Session end: forget what was reported, and drop a read still running."""
        self._last_read = None
        self._reported.clear()
        self._pending = None

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _collect(self) -> list[ContextEvent]:
        if self._pending is None or not self._pending[0].done():
            return []
        future, looked_at = self._pending
        self._pending = None
        return self._report(future.result(), looked_at)  # a failed read raises here

    def _look(self) -> _Seen | None:
        """On the worker: capture, read and classify; the image and text end here."""
        image = self._capture()
        if image is None or image.title.startswith(OWN_TITLE):
            return None
        kind = self._rules.classify_screen_text(self._reader.read(image))
        return None if kind is None else (image.handle, image.title, kind)

    def _report(self, seen: _Seen | None, t: float) -> list[ContextEvent]:
        if seen is None or seen in self._reported:  # nothing, or already reported
            return []
        self._reported.add(seen)
        _, title, kind = seen
        return [ContextEvent(t=t, kind=kind, detail=f"seen on screen: {title}")]


class WindowsOcr:
    """``Windows.Media.Ocr`` with the user's profile languages. Created lazily."""

    __slots__ = ("_engine",)

    def __init__(self) -> None:
        self._engine: Any = None

    def read(self, image: WindowImage) -> str:
        return asyncio.run(self._read(image))

    async def _read(self, image: WindowImage) -> str:
        _load_qt_runtime_first()
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.security.cryptography import CryptographicBuffer

        if self._engine is None:
            self._engine = OcrEngine.try_create_from_user_profile_languages()
            if self._engine is None:
                raise RuntimeError("Windows has no OCR language installed")
        limit = int(OcrEngine.max_image_dimension)
        if image.width > limit or image.height > limit:
            return ""  # larger than the engine accepts; a desktop window rarely is
        buffer = CryptographicBuffer.create_from_byte_array(image.bgra)
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            buffer, BitmapPixelFormat.BGRA8, image.width, image.height
        )
        result = await self._engine.recognize_async(bitmap)
        return str(result.text)


def ocr_status() -> tuple[bool, str]:
    """Can Windows OCR be used on this PC? ``(True, "on (en-US)")`` or ``(False, why)``.

    ``Windows.Media.Ocr`` needs no package identity (unlike the Windows App SDK's
    TextRecognizer); what differs between PCs is whether the bindings and an OCR language
    are installed.
    """
    if sys.platform != "win32":
        return False, "screen text needs Windows"
    _load_qt_runtime_first()
    try:
        from winrt.windows.media.ocr import OcrEngine
    except ImportError:
        return False, "OCR support is not installed (uv sync --extra context)"
    try:
        engine = OcrEngine.try_create_from_user_profile_languages()
    except Exception as exc:  # the OCR service itself failed to start
        return False, f"Windows OCR failed to start: {exc}"
    if engine is None:
        return False, ("no OCR language installed (Settings > Time & language > Language: "
                       "add Optical character recognition)")  # fmt: skip
    return True, f"on ({engine.recognizer_language.language_tag})"


def _load_qt_runtime_first() -> None:
    """winrt bundles an older ``msvcp140.dll``; if it loads before Qt's copy, importing Qt
    later crashes the process (access violation). Load Qt's first when Qt is installed."""
    with contextlib.suppress(ImportError):
        import PySide6.QtCore  # noqa: F401


def capture_active_window() -> WindowImage | None:
    """The foreground window's pixels, or None (no window, minimised, or zero-sized)."""
    import mss

    from chaukas.context.win32 import foreground_window, window_rect

    foreground = foreground_window()
    if foreground is None:
        return None
    handle, title = foreground
    rect = window_rect(handle)
    if rect is None:
        return None
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    if width < 8 or height < 8:
        return None
    factory = getattr(mss, "MSS", None) or mss.mss  # MSS since mss 10; mss() before
    with factory() as screen:
        shot = screen.grab({"left": left, "top": top, "width": width, "height": height})
        return WindowImage(handle=handle, title=title, width=shot.width, height=shot.height,
                           bgra=bytes(shot.bgra))  # fmt: skip
