from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaukas import __version__
from chaukas.app import EXIT_CONFIG_ERROR, EXIT_OK, main


def test_check_config_prints_the_merged_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-config"]) == EXIT_OK
    printed = json.loads(capsys.readouterr().out)
    assert printed["engine"]["thresholds"]["critical"] == 0.7


def test_check_config_applies_overrides(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    override = tmp_path / "eval.yaml"
    override.write_text("ablation:\n  use_llm: false\n", encoding="utf-8")
    assert main(["check-config", "--config", str(override)]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["ablation"]["use_llm"] is False


def test_check_config_reports_invalid_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    override = tmp_path / "bad.yaml"
    override.write_text("engine:\n  thresholds:\n    warning: 0.9\n", encoding="utf-8")
    assert main(["check-config", "--config", str(override)]) == EXIT_CONFIG_ERROR
    assert "thresholds must increase" in capsys.readouterr().err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out
