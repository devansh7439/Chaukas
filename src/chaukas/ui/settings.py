"""The user's own settings: language, trusted contact, capture exclusion.

Saved as JSON in the user's app-data folder, on this PC only. A missing or damaged file
gives defaults rather than an error: Chaukas must always start.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Final

from chaukas.ui.copy import Language

logger = logging.getLogger(__name__)

_NOT_DIALABLE: Final = re.compile(r"[^0-9+\- ]")
_MAX_NAME: Final = 40
_LANGUAGES: Final = ("en", "hi")


@dataclass(frozen=True, slots=True)
class UserSettings:
    language: Language = "en"
    contact_name: str = ""
    contact_number: str = ""
    capture_exclusion: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "contact_name", self.contact_name.strip()[:_MAX_NAME])
        object.__setattr__(
            self, "contact_number", _NOT_DIALABLE.sub("", self.contact_number).strip()
        )


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "Chaukas" / "settings.json"


def load_settings(path: Path | None = None) -> UserSettings:
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return UserSettings()
    except (OSError, ValueError):
        logger.warning("settings file %s is unreadable; using defaults", path)
        return UserSettings()
    if not isinstance(data, dict):
        return UserSettings()
    return UserSettings(**_valid_fields(data))


def save_settings(settings: UserSettings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2),
                         encoding="utf-8")  # fmt: skip
    os.replace(temporary, path)


def _valid_fields(data: dict[str, Any]) -> dict[str, Any]:
    known = {field.name: field for field in fields(UserSettings)}
    kept: dict[str, Any] = {}
    for name, value in data.items():
        if name not in known:
            continue
        if name == "language" and value not in _LANGUAGES:
            continue
        if name == "capture_exclusion" and not isinstance(value, bool):
            continue
        if name in ("contact_name", "contact_number") and not isinstance(value, str):
            continue
        kept[name] = value
    return kept
