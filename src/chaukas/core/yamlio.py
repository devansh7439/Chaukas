"""YAML loading shared by configuration, the lexicon and chain templates."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from chaukas.core.errors import ConfigError

RESOURCE_PACKAGE = "chaukas.resources"


def read_resource_mapping(name: str) -> dict[str, Any]:
    """Parse a YAML mapping shipped inside the package."""
    text = files(RESOURCE_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    return parse_mapping(text, f"packaged {name}")


def read_file_mapping(path: Path, what: str) -> dict[str, Any]:
    """Parse a YAML mapping from disk; ``what`` names the file in error messages."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {what} {path}: {exc}") from exc
    return parse_mapping(text, str(path))


def parse_mapping(text: str, origin: str) -> dict[str, Any]:
    """Parse YAML text that must be a mapping. An empty document is an empty mapping."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{origin} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{origin} must contain a mapping at the top level")
    return data
