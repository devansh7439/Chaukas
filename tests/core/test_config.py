from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from chaukas.core.config import ChaukasConfig, EngineConfig, deep_merge, load_config
from chaukas.core.errors import ConfigError
from chaukas.core.models import SignalKind


def test_packaged_defaults_load_and_match_the_blueprint() -> None:
    config = load_config()
    assert isinstance(config, ChaukasConfig)
    thresholds = config.engine.thresholds
    assert (thresholds.notice, thresholds.warning, thresholds.critical) == (0.20, 0.45, 0.70)
    assert config.engine.weights[SignalKind.ISOLATION] == 0.9
    assert SignalKind.USER_DIGITS_SPOKEN not in config.engine.weights
    assert config.ablation.use_llm
    assert config.ablation.use_action_gate
    assert config.ablation.use_sequence
    assert config.ui.capture_exclusion is False
    assert config.privacy.session_idle_end_s == 1800


def test_config_is_immutable() -> None:
    config = load_config()
    with pytest.raises(ValidationError):
        config.engine.thresholds.warning = 0.5  # type: ignore[misc]


def test_mapping_override_is_deep_merged() -> None:
    config = load_config({"engine": {"thresholds": {"warning": 0.5}}})
    assert config.engine.thresholds.warning == 0.5
    assert config.engine.thresholds.notice == 0.20


def test_file_overrides_apply_in_order(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    first.write_text("ablation:\n  use_llm: false\nui:\n  language: hi\n", encoding="utf-8")
    second = tmp_path / "second.yaml"
    second.write_text("ablation:\n  use_llm: true\n", encoding="utf-8")
    config = load_config(first, second)
    assert config.ablation.use_llm is True
    assert config.ui.language == "hi"


def test_empty_override_file_changes_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert load_config(empty) == load_config()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"engine": {"thresholds": {"warning": 0.8}}}, "thresholds must increase"),
        ({"engine": {"gates": {"action_none": 0.9}}}, "action gates must satisfy"),
        ({"signals": {"weak": 0.55}}, "tier confidences must increase"),
        ({"signals": {"digit_min": 9}}, "digit_min must not exceed digit_max"),
        ({"engine": {"weights": {"threat": 1.5}}}, "less than or equal to 1"),
        ({"engine": {"weights": {"user_digits_spoken": 0.5}}}, "extra="),
        ({"audio": {"sample_rate": 0}}, "greater than 0"),
        ({"ui": {"theme": "dark"}}, "Extra inputs are not permitted"),
        ({"ui": {"language": "fr"}}, "ui.language"),
    ],
)
def test_invalid_overrides_raise_config_error(override: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(override)


def test_weights_must_cover_every_pressure_tactic() -> None:
    data = load_config().engine.model_dump()
    del data["weights"][SignalKind.CREDENTIAL_REQUEST]
    with pytest.raises(ValidationError, match="missing="):
        EngineConfig.model_validate(data)


def test_unreadable_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("engine: [unclosed", "not valid YAML"),
        ("- a\n- b\n", "mapping at the top level"),
    ],
)
def test_malformed_yaml_raises_config_error(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_deep_merge_replaces_lists_and_leaves_inputs_untouched() -> None:
    base = {"a": {"b": 1, "c": [1, 2]}, "d": 1}
    override = {"a": {"c": [3]}, "e": 2}
    assert deep_merge(base, override) == {"a": {"b": 1, "c": [3]}, "d": 1, "e": 2}
    assert base == {"a": {"b": 1, "c": [1, 2]}, "d": 1}
    assert override == {"a": {"c": [3]}, "e": 2}
