"""Thin Windows API readers via ctypes (no pywin32, so no extra ARM64 wheel to find).

* ``foreground_window``: the active window's handle and title.
* ``downloads_folder``: the Downloads known folder, wherever OneDrive moved it.
* ``file_version_strings``: CompanyName / ProductName from an executable's version info,
  which catches renamed remote-access installers.
"""

from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Final

_FOLDERID_DOWNLOADS: Final = uuid.UUID("374DE290-123F-4565-9164-39C4925E467B")
_VERSION_KEYS: Final = ("CompanyName", "ProductName", "FileDescription", "OriginalFilename")


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )

    @classmethod
    def from_uuid(cls, value: uuid.UUID) -> _GUID:
        return cls.from_buffer_copy(value.bytes_le)


def foreground_window() -> tuple[int, str] | None:
    """(handle, title) of the foreground window, or None if there is none."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return int(hwnd), buffer.value


def downloads_folder() -> Path:
    """The Downloads known folder; ``~/Downloads`` if the API is unavailable."""
    fallback = Path.home() / "Downloads"
    if sys.platform != "win32":
        return fallback
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    shell32.SHGetKnownFolderPath.argtypes = (
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    )
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    path = ctypes.c_wchar_p()
    guid = _GUID.from_uuid(_FOLDERID_DOWNLOADS)
    result = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))
    try:
        if result != 0 or not path.value:
            return fallback
        return Path(path.value)
    finally:
        ole32.CoTaskMemFree(path)


def file_version_strings(path: Path) -> dict[str, str]:
    """Version-info strings of an executable; empty if it has none."""
    if sys.platform != "win32":
        return {}
    version = ctypes.WinDLL("version")
    version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
    version.GetFileVersionInfoW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    version.VerQueryValueW.argtypes = (
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    )
    handle = wintypes.DWORD()
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
    if not size:
        return {}
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, data):
        return {}

    pointer = ctypes.c_void_p()
    length = wintypes.UINT()
    if not version.VerQueryValueW(
        data, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)
    ):
        return {}
    pairs = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD * 2))
    count = length.value // ctypes.sizeof(wintypes.WORD * 2)
    translations = [(pairs[i][0], pairs[i][1]) for i in range(count)] or [(0x0409, 0x04B0)]

    strings: dict[str, str] = {}
    for language, codepage in translations:
        for key in _VERSION_KEYS:
            if key in strings:
                continue
            query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{key}"
            found = version.VerQueryValueW(data, query, ctypes.byref(pointer), ctypes.byref(length))
            if found and pointer.value:
                value = ctypes.wstring_at(pointer.value, length.value).rstrip("\x00").strip()
                if value:
                    strings[key] = value
    return strings
