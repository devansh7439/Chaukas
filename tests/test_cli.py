from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaukas import __version__
from chaukas.app import EXIT_ERROR, EXIT_OK, main

CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


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
    assert main(["check-config", "--config", str(override)]) == EXIT_ERROR
    assert "thresholds must increase" in capsys.readouterr().err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_replay_prints_a_timeline(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["replay", str(CASES_DIR / "DA01.yaml"), "--ablation", "D"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "DA01" in out
    assert "CRITICAL" in out
    assert "first critical" in out


def test_replay_reports_a_missing_case(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["replay", str(tmp_path / "nope.yaml")]) == EXIT_ERROR
    assert "cannot read case" in capsys.readouterr().err


def test_eval_prints_outcomes_and_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval", str(CASES_DIR), "--split", "dev", "--ablation", "D"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "critical before harm" in out
    assert "DA01" in out
    assert "95% CI" in out


def test_ablate_prints_a_comparison_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ablate", str(CASES_DIR)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "config" in out
    for name in ("A", "B", "C", "D", "E"):
        assert f"\n{name}  " in out or out.startswith(f"{name}  ")


SCRIPTED_NOTE = "script the LLM's verdict"

CASE_WITHOUT_LLM = """\
case_id: BNX
category: benign
scenario: family_call
split: dev
author: test
expected: {max_level: quiet, acceptable_levels: [quiet, notice], objective: none}
timeline:
  - {at: 0.0, caller: "Beta, khana kha liya?"}
"""


def test_ablate_flags_cases_that_script_the_llm(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ablate", str(CASES_DIR)]) == EXIT_OK
    out = capsys.readouterr().out
    assert f"4 of 4 cases {SCRIPTED_NOTE}" in out
    assert "BN01, BN07, CT01, DA01" in out
    assert "B, C and D" in out


def test_eval_flags_scripted_llm_only_when_the_config_uses_the_llm(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["eval", str(CASES_DIR), "--ablation", "D"]) == EXIT_OK
    assert SCRIPTED_NOTE in capsys.readouterr().out
    assert main(["eval", str(CASES_DIR), "--ablation", "E"]) == EXIT_OK
    assert SCRIPTED_NOTE not in capsys.readouterr().out


def test_no_note_when_no_case_scripts_the_llm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "BNX.yaml").write_text(CASE_WITHOUT_LLM, encoding="utf-8")
    assert main(["ablate", str(tmp_path)]) == EXIT_OK
    assert SCRIPTED_NOTE not in capsys.readouterr().out
