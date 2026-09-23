"""Hide a window from screen capture (blueprint 6.8), off by default.

``SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`` hides the window from an attacker's
screen share, and also from OBS, Game Bar and Snipping Tool on this PC (and possibly the
Device Cloud viewer). It only affects capture software that respects the Windows setting,
and an excluded window still receives input. Apply it after the window is shown.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Final

_WDA_NONE: Final = 0x00
_WDA_EXCLUDEFROMCAPTURE: Final = 0x11


def set_capture_excluded(hwnd: int, excluded: bool) -> bool:
    """True if Windows accepted the change."""
    if sys.platform != "win32" or not hwnd:
        return False
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    affinity = _WDA_EXCLUDEFROMCAPTURE if excluded else _WDA_NONE
    return bool(user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), affinity))
