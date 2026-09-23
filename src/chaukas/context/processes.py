"""Remote-access tools starting (blueprint 6.5).

Each poll diffs the process list against the previous one. Only processes that appear
after the first poll count: a tool left running from last week says nothing about this
call. Version-info strings are read only for new processes, so a poll stays cheap.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from chaukas.context.rules import ContextRules
from chaukas.core.models import ContextEvent, ContextKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    name: str
    exe: Path | None
    company: str = ""
    product: str = ""


ProcessLister = Callable[[], Iterable[ProcessInfo]]
VersionReader = Callable[[Path], dict[str, str]]


def list_processes() -> list[ProcessInfo]:
    """Running processes via psutil (the ``context`` extra)."""
    import psutil

    processes: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        info = proc.info
        exe = info.get("exe")
        processes.append(
            ProcessInfo(
                pid=info["pid"], name=info.get("name") or "", exe=Path(exe) if exe else None
            )
        )
    return processes


def _default_version_reader(path: Path) -> dict[str, str]:
    if sys.platform != "win32":
        return {}
    from chaukas.context.win32 import file_version_strings

    return file_version_strings(path)


class ProcessWatcher:
    __slots__ = ("_known", "_lister", "_read_version", "_rules")

    def __init__(
        self,
        rules: ContextRules,
        lister: ProcessLister,
        version_reader: VersionReader = _default_version_reader,
    ) -> None:
        self._rules = rules
        self._lister = lister
        self._read_version = version_reader
        self._known: set[int] | None = None

    def poll(self, now: float) -> list[ContextEvent]:
        current = {process.pid: process for process in self._lister()}
        known = self._known
        self._known = set(current)
        if known is None:  # the first poll is the baseline
            return []
        events = []
        for pid in sorted(current.keys() - known):
            process = self._with_version(current[pid])
            if self._rules.is_remote_tool(
                process.name, company=process.company, product=process.product
            ):
                events.append(
                    ContextEvent(
                        t=now, kind=ContextKind.REMOTE_APP_STARTED, detail=_detail(process)
                    )
                )
        return events

    def reset(self) -> None:
        self._known = None

    def _with_version(self, process: ProcessInfo) -> ProcessInfo:
        if process.company or process.product or process.exe is None:
            return process
        try:
            strings = self._read_version(process.exe)
        except OSError:
            logger.debug("no version info for %s", process.exe)
            return process
        return replace(
            process,
            company=strings.get("CompanyName", ""),
            product=strings.get("ProductName", ""),
        )


def _detail(process: ProcessInfo) -> str:
    if process.product and process.product.casefold() not in process.name.casefold():
        return f"{process.name} ({process.product})"
    return process.name
