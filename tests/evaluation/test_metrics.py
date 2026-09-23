from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from chaukas.core.models import Level
from chaukas.evaluation.ablation import ABLATIONS, config_for
from chaukas.evaluation.cases import Category, load_cases
from chaukas.evaluation.metrics import (
    CaseOutcome,
    Proportion,
    score_case,
    summarise,
    wilson_interval,
)
from chaukas.evaluation.report import (
    format_ablation,
    format_outcomes,
    format_run,
    format_summary,
)
from chaukas.evaluation.runner import run_case
from chaukas.llm.client import ChatResult
from chaukas.llm.reasoner import Reasoner
from chaukas.signals.lexicon import Lexicon


@pytest.fixture(scope="module")
def outcomes(cases_dir: Path) -> list[CaseOutcome]:
    config = config_for("D")
    lexicon = Lexicon.load()
    return [
        score_case(run_case(case, config=config, lexicon=lexicon)) for case in load_cases(cases_dir)
    ]


def by_id(outcomes: list[CaseOutcome], case_id: str) -> CaseOutcome:
    return next(outcome for outcome in outcomes if outcome.case_id == case_id)


class TestScoring:
    def test_attack_outcome(self, outcomes: list[CaseOutcome]) -> None:
        da01 = by_id(outcomes, "DA01")
        assert da01.category is Category.ATTACK
        assert da01.detected
        assert da01.critical_before_harm
        assert da01.objective_correct
        assert da01.within_acceptable
        assert da01.false_alarm is None
        assert da01.warning_latency == pytest.approx(0.4, abs=0.1)  # expected_warning was 19.5

    def test_benign_outcomes(self, outcomes: list[CaseOutcome]) -> None:
        news = by_id(outcomes, "BN01")
        assert news.false_alarm is False
        assert news.detected is None
        assert news.within_acceptable
        assert news.max_level is Level.QUIET
        support = by_id(outcomes, "BN07")
        assert support.max_level is Level.NOTICE
        assert support.false_alarm is False

    def test_summary_counts(self, outcomes: list[CaseOutcome]) -> None:
        summary = summarise(outcomes)
        assert summary.cases == 4
        assert summary.attacks == 2
        assert summary.benign == 2
        assert (summary.detection.hits, summary.detection.total) == (2, 2)
        assert (summary.false_alarms.hits, summary.false_alarms.total) == (0, 2)
        assert summary.within_acceptable.hits == 4
        assert summary.warning_latency_median is not None


class TestProportions:
    @pytest.mark.parametrize(
        ("hits", "total", "low", "high"),
        [(18, 18, 0.82, 1.00), (2, 18, 0.03, 0.33), (0, 5, 0.00, 0.43), (9, 18, 0.29, 0.71)],
    )
    def test_wilson_interval(self, hits: int, total: int, low: float, high: float) -> None:
        got_low, got_high = wilson_interval(hits, total)
        assert got_low == pytest.approx(low, abs=0.01)
        assert got_high == pytest.approx(high, abs=0.01)

    def test_invalid_inputs(self) -> None:
        with pytest.raises(ValueError, match="total"):
            wilson_interval(1, 0)
        with pytest.raises(ValueError, match="outside"):
            wilson_interval(5, 4)

    def test_formatting(self) -> None:
        assert str(Proportion(2, 18)) == "2/18 (11%, 95% CI 3%-33%)"
        assert str(Proportion(0, 0)) == "n/a"
        assert Proportion(0, 0).ratio is None
        assert Proportion(0, 0).interval is None

    def test_empty_summary(self) -> None:
        summary = summarise([])
        assert summary.cases == 0
        assert summary.warning_latency_median is None
        assert str(summary.detection) == "n/a"


class TestAblationConfigs:
    def test_each_configuration_sets_its_flags(self) -> None:
        for name, flags in ABLATIONS.items():
            ablation = config_for(name).ablation
            assert ablation.use_llm is flags["use_llm"], name
            assert ablation.use_action_gate is flags["use_action_gate"], name
            assert ablation.use_sequence is flags["use_sequence"], name

    def test_ablation_wins_over_other_overrides(self) -> None:
        config = config_for("A", {"ablation": {"use_llm": True}})
        assert config.ablation.use_llm is False

    def test_unknown_name(self) -> None:
        with pytest.raises(KeyError, match="unknown ablation"):
            config_for("Z")


class TestReports:
    def test_run_report(self, cases_dir: Path) -> None:
        cases = load_cases(cases_dir)
        run = run_case(cases[3], config=config_for("D"), lexicon=Lexicon.load())
        text = format_run(run)
        assert "DA01" in text
        assert "CRITICAL" in text
        assert "transfer money" in text

    def test_outcome_and_ablation_tables(self, outcomes: list[CaseOutcome]) -> None:
        text = format_outcomes(outcomes, summarise(outcomes))
        assert "critical before harm" in text
        assert "DA01" in text
        table = format_ablation({name: summarise(outcomes) for name in sorted(ABLATIONS)})
        assert table.count("\n") == len(ABLATIONS) + 1
        assert "false alarms" in table


class _AlternatingChat:
    """Every other answer is unusable; usable answers quote one real and one invented line."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: Sequence[Mapping[str, str]]) -> ChatResult:
        self.calls += 1
        if self.calls % 2 == 0:
            return ChatResult(content="I think this is a scam.", latency_s=1.0)
        caller_line = next(
            line for line in messages[1]["content"].splitlines() if "][CALLER] " in line
        )
        line_id = int(caller_line.split("[L", 1)[1].split(" ", 1)[0])
        quote = " ".join(caller_line.split("][CALLER] ", 1)[1].split()[:3])
        reply = {
            "addressed_to_user": True,
            "suspected_objective": "unclear",
            "tactics": [
                {"name": "authority", "line": line_id, "evidence": quote, "confidence": 0.6},
                {"name": "threat", "line": line_id, "evidence": "zzz qqq", "confidence": 0.6},
            ],
        }
        return ChatResult(content=json.dumps(reply), latency_s=1.0)


class TestLLMMetrics:
    def test_validity_rejections_and_call_rate(self, cases_dir: Path) -> None:
        config = config_for("D")
        lexicon = Lexicon.load()
        reasoner = Reasoner(_AlternatingChat(), config)
        outcomes = [
            score_case(run_case(case, config=config, lexicon=lexicon, reasoner=reasoner))
            for case in load_cases(cases_dir)
        ]
        calls = sum(outcome.llm_calls for outcome in outcomes)
        valid = sum(outcome.llm_valid for outcome in outcomes)
        assert calls > 0
        assert 0 < valid < calls
        summary = summarise(outcomes)
        assert summary.llm_json_validity == Proportion(valid, calls)
        assert summary.llm_evidence_rejected.total == 2 * valid
        assert summary.llm_evidence_rejected.hits == valid  # the invented quote, every time
        assert summary.llm_calls_per_minute_benign is not None
        text = format_summary(summary)
        assert "LLM JSON validity" in text
        assert "LLM evidence rejected" in text

    def test_no_llm_rows_without_llm_calls(self, outcomes: list[CaseOutcome]) -> None:
        summary = summarise(outcomes)
        assert summary.llm_json_validity == Proportion(0, 0)
        assert summary.llm_calls_per_minute_benign is None
        assert "LLM" not in format_summary(summary)
