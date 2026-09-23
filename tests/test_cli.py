from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

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


class _ModelHandler(BaseHTTPRequestHandler):
    """A stand-in OpenAI-compatible server that says every call is addressed to the user."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        content = json.dumps({"addressed_to_user": True, "suspected_objective": "unclear"})
        data = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def model_config(tmp_path: Path) -> Iterator[Path]:
    httpd = HTTPServer(("127.0.0.1", 0), _ModelHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    override = tmp_path / "llm.yaml"
    override.write_text(
        f"llm:\n  base_url: http://127.0.0.1:{httpd.server_address[1]}/v1\n", encoding="utf-8"
    )
    yield override
    httpd.shutdown()
    httpd.server_close()


def test_eval_with_a_real_model_reports_llm_metrics(
    model_config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["eval", str(CASES_DIR), "--ablation", "D", "--llm", "--config", str(model_config)]
    assert main(args) == EXIT_OK
    out = capsys.readouterr().out
    assert "LLM JSON validity" in out
    assert SCRIPTED_NOTE not in out  # scripted verdicts are ignored with a real model


def test_replay_lists_llm_calls(model_config: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["replay", str(CASES_DIR / "DA01.yaml"), "--ablation", "D", "--llm",
            "--config", str(model_config)]  # fmt: skip
    assert main(args) == EXIT_OK
    assert "LLM call at" in capsys.readouterr().out


def test_a_cached_perception_pass_replays_offline(
    model_config: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = tmp_path / "cache"
    common = ["eval", str(CASES_DIR), "--ablation", "D", "--llm", "--llm-cache", str(cache)]
    assert main([*common, "--config", str(model_config)]) == EXIT_OK
    online = capsys.readouterr().out
    assert any(cache.glob("*.json"))
    # No server this time: every answer must come from the cache.
    offline_config = tmp_path / "offline.yaml"
    offline_config.write_text("llm:\n  base_url: http://127.0.0.1:9/v1\n", encoding="utf-8")
    assert main([*common, "--llm-offline", "--config", str(offline_config)]) == EXIT_OK
    assert capsys.readouterr().out == online


def test_offline_needs_a_cache(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["eval", str(CASES_DIR), "--llm", "--llm-offline"])
    assert "--llm-cache" in capsys.readouterr().err


def test_ui_screenshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("PySide6")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    target = tmp_path / "ui.png"
    args = ["ui", "--demo", str(CASES_DIR / "CT01.yaml"), "--screenshot", str(target),
            "--at", "10", "--size", "1280x820"]  # fmt: skip
    assert main(args) == EXIT_OK
    assert target.is_file()


def test_ui_rejects_a_bad_size(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["ui", "--size", "big"])
    assert "WIDTHxHEIGHT" in capsys.readouterr().err
