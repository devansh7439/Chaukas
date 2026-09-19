from __future__ import annotations

from pathlib import Path

import pytest

from chaukas.signals.lexicon import Lexicon

CASES_DIR = Path(__file__).resolve().parents[2] / "eval" / "cases"


@pytest.fixture(scope="session")
def cases_dir() -> Path:
    return CASES_DIR


@pytest.fixture(scope="session")
def lexicon() -> Lexicon:
    return Lexicon.load()
