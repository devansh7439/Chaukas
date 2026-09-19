from __future__ import annotations

import pytest

from chaukas.core.config import load_config
from chaukas.core.models import Level
from chaukas.engine.levels import LevelController

ENGINE = load_config().engine  # margin 0.10, hold 30 s, dismissal 180 s


@pytest.fixture
def controller() -> LevelController:
    return LevelController(ENGINE.thresholds, ENGINE.rules)


def test_escalates_immediately(controller: LevelController) -> None:
    assert controller.update(0.0, Level.WARNING, 0.5) is Level.WARNING
    assert controller.update(1.0, Level.CRITICAL, 0.8) is Level.CRITICAL


def test_de_escalates_only_after_the_hold(controller: LevelController) -> None:
    controller.update(0.0, Level.WARNING, 0.5)
    assert controller.update(1.0, Level.NOTICE, 0.30) is Level.WARNING  # below 0.35 since t=1
    assert controller.update(30.0, Level.NOTICE, 0.30) is Level.WARNING
    assert controller.update(31.0, Level.NOTICE, 0.30) is Level.NOTICE


def test_a_score_near_the_threshold_restarts_the_hold(controller: LevelController) -> None:
    controller.update(0.0, Level.WARNING, 0.5)
    controller.update(1.0, Level.NOTICE, 0.30)
    controller.update(20.0, Level.NOTICE, 0.40)  # not clearly below 0.35: hold restarts
    controller.update(40.0, Level.NOTICE, 0.30)
    assert controller.update(69.0, Level.NOTICE, 0.30) is Level.WARNING
    assert controller.update(70.0, Level.NOTICE, 0.30) is Level.NOTICE


def test_drops_straight_to_the_current_raw_level(controller: LevelController) -> None:
    controller.update(0.0, Level.CRITICAL, 0.9)
    controller.update(1.0, Level.QUIET, 0.1)
    assert controller.update(31.0, Level.QUIET, 0.1) is Level.QUIET


def test_rule_based_critical_with_a_low_score_still_holds(controller: LevelController) -> None:
    controller.update(0.0, Level.CRITICAL, 0.46)
    controller.update(1.0, Level.WARNING, 0.46)
    assert controller.update(20.0, Level.WARNING, 0.46) is Level.CRITICAL
    assert controller.update(31.0, Level.WARNING, 0.46) is Level.WARNING


def test_dismissal(controller: LevelController) -> None:
    controller.update(0.0, Level.CRITICAL, 0.9)
    controller.dismiss(5.0, change_marker=3)
    assert controller.is_dismissed(10.0, change_marker=3)
    assert not controller.is_dismissed(10.0, change_marker=4)  # something new happened
    assert not controller.is_dismissed(185.0, change_marker=3)  # expired
    controller.update(11.0, Level.CRITICAL_RECOVERY, 0.9)
    assert not controller.is_dismissed(12.0, change_marker=3)  # a different level now


def test_dismissing_while_quiet_does_nothing(controller: LevelController) -> None:
    controller.dismiss(0.0, change_marker=0)
    assert not controller.is_dismissed(1.0, change_marker=0)


def test_reset(controller: LevelController) -> None:
    controller.update(0.0, Level.CRITICAL, 0.9)
    controller.reset()
    assert controller.level is Level.QUIET
