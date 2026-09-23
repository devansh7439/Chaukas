"""End-to-end replay: case script through signals, engine and levels."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from chaukas.core.models import Level, Objective
from chaukas.evaluation.ablation import config_for
from chaukas.evaluation.cases import Case, load_case
from chaukas.evaluation.runner import CaseRun, run_case
from chaukas.llm.client import ChatResult
from chaukas.llm.reasoner import Reasoner
from chaukas.signals.lexicon import Lexicon


def replay(case: Case, lexicon: Lexicon, ablation: str = "D") -> CaseRun:
    return run_case(case, config=config_for(ablation), lexicon=lexicon)


@pytest.fixture(scope="module")
def cases(cases_dir: Path) -> dict[str, Case]:
    return {path.stem: load_case(path) for path in sorted(cases_dir.glob("*.yaml"))}


def test_digital_arrest_escalates_step_by_step(cases: dict[str, Case], lexicon: Lexicon) -> None:
    run = replay(cases["DA01"], lexicon)
    assert [snapshot.level for snapshot in run.transitions] == [
        Level.NOTICE,
        Level.WARNING,
        Level.CRITICAL,
    ]
    assert run.objective_when(Level.WARNING) is Objective.MONEY_TRANSFER
    harm = run.case.harm_t
    critical = run.first_time_at_least(Level.CRITICAL)
    assert harm is not None
    assert critical is not None
    assert critical < harm  # the warning arrives before the money moves


def test_credential_theft_warns_before_the_code_is_read_and_then_recovers(
    cases: dict[str, Case], lexicon: Lexicon
) -> None:
    run = replay(cases["CT01"], lexicon)
    critical = run.first_time_at_least(Level.CRITICAL)
    harm = run.case.harm_t
    assert critical is not None
    assert harm is not None
    assert critical < harm
    assert run.max_level is Level.CRITICAL_RECOVERY
    assert run.objective_when(Level.CRITICAL) is Objective.CREDENTIAL_DISCLOSURE


def test_news_report_stays_quiet_because_of_the_llm(
    cases: dict[str, Case], lexicon: Lexicon
) -> None:
    with_llm = replay(cases["BN01"], lexicon, ablation="D")
    without_llm = replay(cases["BN01"], lexicon, ablation="E")
    assert with_llm.max_level is Level.QUIET
    assert without_llm.max_level is Level.NOTICE  # keywords alone still raise a notice


def test_legit_it_support_never_warns(cases: dict[str, Case], lexicon: Lexicon) -> None:
    for ablation in ("D", "E"):
        run = replay(cases["BN07"], lexicon, ablation=ablation)
        assert run.max_level is Level.NOTICE, ablation


def test_keywords_only_configuration_is_noisier(cases: dict[str, Case], lexicon: Lexicon) -> None:
    # Config A has no action gate and no sequence gate, so the news bulletin escalates.
    assert replay(cases["BN01"], lexicon, ablation="A").max_level >= Level.WARNING


def test_replay_is_deterministic(cases: dict[str, Case], lexicon: Lexicon) -> None:
    first = replay(cases["DA01"], lexicon)
    second = replay(cases["DA01"], lexicon)
    trace = [(s.t, s.level, round(s.state.score, 9)) for s in first.snapshots]
    assert trace == [(s.t, s.level, round(s.state.score, 9)) for s in second.snapshots]


def test_snapshots_cover_the_settle_period(cases: dict[str, Case], lexicon: Lexicon) -> None:
    run = replay(cases["DA01"], lexicon)
    assert run.snapshots[-1].t >= run.case.end_time
    assert run.final_state is not None


class FixedChat:
    """A stand-in model that always gives the same answer after a fixed latency."""

    def __init__(self, reply: dict[str, object], latency_s: float = 3.0) -> None:
        self.content = json.dumps(reply)
        self.latency_s = latency_s
        self.calls = 0

    def chat(self, messages: Sequence[Mapping[str, str]]) -> ChatResult:
        self.calls += 1
        return ChatResult(content=self.content, latency_s=self.latency_s)


ADDRESSED = {"addressed_to_user": True, "suspected_objective": "money_transfer"}


def with_model(case: Case, lexicon: Lexicon, chat: FixedChat, ablation: str = "D") -> CaseRun:
    config = config_for(ablation)
    return run_case(case, config=config, lexicon=lexicon, reasoner=Reasoner(chat, config))


def test_a_real_model_replaces_scripted_verdicts(cases: dict[str, Case], lexicon: Lexicon) -> None:
    # BN01 scripts "not addressed to the user"; this model disagrees, so the news escalates.
    run = with_model(cases["BN01"], lexicon, FixedChat(ADDRESSED))
    assert run.max_level >= Level.NOTICE
    assert run.llm_outcomes


def test_llm_answers_land_after_their_measured_latency(
    cases: dict[str, Case], lexicon: Lexicon
) -> None:
    run = with_model(cases["DA01"], lexicon, FixedChat(ADDRESSED, latency_s=4.0))
    first = run.llm_outcomes[0]
    assert first.t_available == pytest.approx(first.t_request + 4.0)
    assessed = [s.t for s in run.snapshots if s.state.llm_assessed]
    assert min(assessed) == pytest.approx(first.t_available)
    assert run.first_time_at_least(Level.CRITICAL) is not None


def test_configurations_without_the_llm_never_call_it(
    cases: dict[str, Case], lexicon: Lexicon
) -> None:
    chat = FixedChat(ADDRESSED)
    run = with_model(cases["DA01"], lexicon, chat, ablation="E")
    assert chat.calls == 0
    assert run.llm_outcomes == ()


def test_calls_are_debounced(cases: dict[str, Case], lexicon: Lexicon) -> None:
    run = with_model(cases["DA01"], lexicon, FixedChat(ADDRESSED, latency_s=1.0))
    starts = [outcome.t_request for outcome in run.llm_outcomes]
    assert all(b - a >= 8.0 for a, b in itertools.pairwise(starts))
