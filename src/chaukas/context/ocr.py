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
from collections.abc import Callable
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


class TriggeredOcr:
    """Reads the active window's text while ``should_read()`` says the call is suspicious."""

    __slots__ = ("_capture", "_interval", "_last_read", "_reader", "_reported", "_rules",
                 "_should_read")  # fmt: skip

    def __init__(
        self,
        rules: ContextRules,
        *,
        should_read: Callable[[], bool],
        capture: Capture,
        reader: TextReader,
        interval_s: float,
    ) -> None:
        self._rules = rules
        self._should_read = should_read
        self._capture = capture
        self._reader = reader
        self._interval = interval_s
        self._last_read: float | None = None
        self._reported: set[tuple[int, str, ContextKind]] = set()

    def poll(self, now: float) -> list[ContextEvent]:
        if not self._should_read():
            return []
        if self._last_read is not None and now - self._last_read < self._interval:
            return []
        self._last_read = now
        image = self._capture()
        if image is None or image.title.startswith(OWN_TITLE):
            return []
        kind = self._rules.classify_screen_text(self._reader.read(image))
        if kind is None:
            return []
        key = (image.handle, image.title, kind)
        if key in self._reported:  # already reported for this window and page
            return []
        self._reported.add(key)
        return [ContextEvent(t=now, kind=kind, detail=f"seen on screen: {image.title}")]

    def reset(self) -> None:
        """Session end."""
        self._last_read = None
        self._reported.clear()


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
