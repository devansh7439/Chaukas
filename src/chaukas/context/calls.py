"""Is a call happening right now? The microphone says so.

Chaukas hears everything the PC plays, so a film or a news report about scams sounds like a
scam call. The difference: during a real call the call app (WhatsApp, Zoom, Teams, Skype, a
browser tab with Meet) holds the microphone; while a video plays, nothing does.

Windows keeps a per-app record of microphone use in its privacy settings (the list behind
Settings > Privacy > Microphone): each app's last start and stop time, where a stop time of
0 means "using it right now". Chaukas's own capture is excluded. Nothing is recorded or
sent; the records are read once a second while protection runs.

The probe answers True (a call app holds the microphone), False (none does) or None (it
cannot tell); only a definite False changes anything, so a failure never lowers protection.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Collection, Mapping
from typing import Final

logger = logging.getLogger(__name__)

Records = Mapping[str, tuple[int, int]]  # app key -> (last start, last stop), FILETIME ticks
_STORE: Final = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


def apps_in_use(records: Records, *, exclude: Collection[str]) -> list[str]:
    """Apps holding the microphone now: started at some point and not stopped since.
    Desktop apps are keyed by their path with "#" for "\\"; ``exclude`` holds paths."""
    excluded = {path.lower() for path in exclude}
    using = []
    for key, (start, stop) in records.items():
        app = key.replace("#", "\\")
        if start and not stop and app.lower() not in excluded:
            using.append(app)
    return using


def read_records(capability: str = "microphone") -> dict[str, tuple[int, int]] | None:
    """This Windows user's records of one capability ("microphone", or the screen-capture
    ones read by ``context/sharing.py``), or None where there are none. Desktop apps are
    listed under "NonPackaged", which is absent until a desktop app has used it."""
    if sys.platform != "win32":
        return None
    import winreg

    records: dict[str, tuple[int, int]] = {}

    def collect(path: str) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                name = winreg.EnumKey(key, i)
                if name == "NonPackaged":
                    continue
                try:
                    with winreg.OpenKey(key, name) as app:
                        start = int(winreg.QueryValueEx(app, "LastUsedTimeStart")[0])
                        stop = int(winreg.QueryValueEx(app, "LastUsedTimeStop")[0])
                except OSError:  # an app that never used the capability has no times
                    continue
                records[name] = (start, stop)

    try:
        collect(rf"{_STORE}\{capability}")
    except OSError:
        return None
    try:
        collect(rf"{_STORE}\{capability}\NonPackaged")
    except FileNotFoundError:
        pass
    except OSError:
        return None
    return records


def microphone_users(*, exclude: Collection[str]) -> list[str] | None:
    """Apps other than ``exclude`` using the microphone now, or None if unknown."""
    records = read_records()
    return None if records is None else apps_in_use(records, exclude=exclude)


def own_executables() -> frozenset[str]:
    """The interpreter paths Chaukas's own microphone capture is recorded under. Windows
    records the resolved path (uv's "cpython-3.12" folder is a link to "cpython-3.12.13"),
    so the resolved forms are included too."""
    paths = {sys.executable, getattr(sys, "_base_executable", sys.executable)}
    paths |= {os.path.realpath(path) for path in paths if path}
    return frozenset(path for path in paths if path)


class CallProbe:
    """True if another app holds the microphone, False if none does, None if unknown."""

    def __init__(
        self,
        *,
        read: Callable[[], Records | None] = read_records,
        exclude: Collection[str] | None = None,
    ) -> None:
        self._read = read
        self._exclude = own_executables() if exclude is None else exclude

    def __call__(self) -> bool | None:
        try:
            records = self._read()
        except OSError:
            logger.warning("the microphone records could not be read; call state unknown")
            return None
        if records is None:
            return None
        return bool(apps_in_use(records, exclude=self._exclude))
