from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chaukas.core.errors import ConfigError
from chaukas.core.models import ContextKind, Objective, SignalKind
from chaukas.engine.templates import load_templates, templates_from_mapping


def test_packaged_templates_match_the_blueprint() -> None:
    templates = load_templates()
    assert [t.name for t in templates] == ["digital_arrest", "remote_access", "credential_theft"]
    assert [round(t.total_weight, 2) for t in templates] == [5.4, 4.2, 3.8]
    digital_arrest = templates[0]
    assert digital_arrest.objective is Objective.MONEY_TRANSFER
    steps = {step.id: step for step in digital_arrest.steps}
    assert steps["control"].signals == {SignalKind.ISOLATION, SignalKind.SURVEILLANCE}
    assert steps["bank_ctx"].events == {ContextKind.BANK_PAGE, ContextKind.TRANSFER_PAGE}
    assert [step.required for step in digital_arrest.steps] == [True, True, True, True, False]


def one_template(**step: Any) -> dict[str, Any]:
    base = {"id": "a", "signals": ["authority"], "weight": 1.0, "required": True}
    base.update({"distinctive": False, **step})
    return {"t": {"objective": "money_transfer", "steps": [base]}}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (one_template(signals=[]), "neither signals nor events"),
        (one_template(weight=0.0), "greater than 0"),
        (one_template(required=False), "at least one required step"),
        (one_template(signals=["gossip"]), "signals"),
        (
            {"t": {"objective": "unclear", "steps": one_template()["t"]["steps"]}},
            "concrete objective",
        ),
        (
            {"t": {"objective": "money_transfer", "steps": one_template()["t"]["steps"] * 2}},
            "duplicate step ids",
        ),
        ({}, "at least one chain template"),
    ],
)
def test_invalid_templates(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        templates_from_mapping(data)


def test_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read chain templates"):
        load_templates(tmp_path / "missing.yaml")
