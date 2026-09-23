"""What the dashboard shows for a given engine state: pure functions, no Qt."""

from __future__ import annotations

import pytest

from chaukas.core.models import (
    ChainState,
    Level,
    Objective,
    Reason,
    RiskComponents,
    RiskState,
    SignalKind,
)
from chaukas.engine.templates import load_templates
from chaukas.ui.copy import TEXT
from chaukas.ui.presenter import (
    chain_view,
    clock,
    evidence_chips,
    history_bars,
    present,
    reason_view,
)

TEMPLATES = load_templates()


def state(level: Level = Level.QUIET, **kwargs: object) -> RiskState:
    fields: dict[str, object] = {
        "t": 65.0,
        "score": 0.45,
        "level": level,
        "objective": Objective.UNCLEAR,
        "components": RiskComponents(pressure=0.78, addressed=1.0, action=0.7, sequence=0.84),
    }
    fields.update(kwargs)
    return RiskState(**fields)  # type: ignore[arg-type]


class TestClock:
    @pytest.mark.parametrize(("t", "text"), [(0.0, "00:00"), (65.4, "01:05"), (3725.0, "62:05")])
    def test_minutes_and_seconds(self, t: float, text: str) -> None:
        assert clock(t) == text


class TestPresent:
    @pytest.mark.parametrize(
        ("level", "key"),
        [
            (Level.QUIET, "quiet"),
            (Level.NOTICE, "notice"),
            (Level.WARNING, "warning"),
            (Level.CRITICAL, "critical"),
            (Level.CRITICAL_RECOVERY, "critical_recovery"),
        ],
    )
    def test_every_level_has_a_headline_and_title_in_both_languages(
        self, level: Level, key: str
    ) -> None:
        for language in ("en", "hi"):
            view = present(state(level), templates=TEMPLATES, language=language, paused=False)
            assert view["level"] == key
            assert view["headline"]
            assert view["levelTitle"]

    def test_percentages_and_objective(self) -> None:
        view = present(
            state(Level.WARNING, objective=Objective.MONEY_TRANSFER),
            templates=TEMPLATES,
            language="en",
            paused=False,
        )
        assert view["scorePercent"] == 45
        assert view["pressurePercent"] == 78
        assert view["objective"] == "Someone on your call may be trying to make you transfer money"
        assert view["callTime"] == "01:05"

    def test_quiet_objective_is_reassuring_not_blank(self) -> None:
        view = present(state(Level.QUIET, objective=Objective.NONE), templates=TEMPLATES,
                       language="en", paused=False)  # fmt: skip
        assert view["objective"] == "Nothing suspicious so far"

    def test_unclear_objective_names_the_pressure(self) -> None:
        view = present(state(Level.NOTICE), templates=TEMPLATES, language="en", paused=False)
        assert view["objective"] == "Someone may be pressuring you"

    def test_alert_shows_only_for_undismissed_alerts_while_listening(self) -> None:
        def alert(level: Level, *, dismissed: bool = False, paused: bool = False) -> bool:
            view = present(state(level, dismissed=dismissed), templates=TEMPLATES,
                           language="en", paused=paused)  # fmt: skip
            return bool(view["alertVisible"])

        assert not alert(Level.QUIET)
        assert alert(Level.NOTICE)
        assert alert(Level.CRITICAL)
        assert not alert(Level.CRITICAL, dismissed=True)
        assert not alert(Level.WARNING, paused=True)

    def test_paused_is_reported(self) -> None:
        view = present(state(), templates=TEMPLATES, language="en", paused=True)
        assert view["paused"] is True
        assert view["statusLine"] == TEXT["status_paused"]["en"]

    def test_fact_lines_for_money_and_credentials(self) -> None:
        money = present(state(Level.CRITICAL, objective=Objective.MONEY_TRANSFER),
                        templates=TEMPLATES, language="en", paused=False)  # fmt: skip
        otp = present(state(Level.CRITICAL, objective=Objective.CREDENTIAL_DISCLOSURE),
                      templates=TEMPLATES, language="en", paused=False)  # fmt: skip
        recovery = present(state(Level.CRITICAL_RECOVERY,
                                 objective=Objective.CREDENTIAL_DISCLOSURE),
                           templates=TEMPLATES, language="en", paused=False)  # fmt: skip
        assert "digital arrest" in money["fact"]
        assert "OTP" in otp["fact"]
        assert "already shared" in recovery["fact"]
        assert money["ignoreWarning"].startswith("If the caller tells you to ignore")


class TestReasons:
    def test_signal_reasons_become_plain_sentences_with_quotes(self) -> None:
        view = reason_view(Reason(t=12.0, label="authority", detail="cbi se"), "en")
        assert view == {
            "time": "00:12",
            "kind": "authority",
            "text": "Caller claimed to be an official",
            "quote": "cbi se",
            "icon": "shield-alert",
        }

    def test_context_reasons_have_no_quote(self) -> None:
        view = reason_view(
            Reason(t=70.0, label="transfer_page", detail="DemoBank (MOCK) - Transfer Funds"), "en"
        )
        assert view["text"] == "A money-transfer page is open"
        assert view["quote"] == "DemoBank (MOCK) - Transfer Funds"
        assert view["icon"] == "monitor"

    @pytest.mark.parametrize("label", [*(k.value for k in SignalKind), "bank_page",
                                       "transfer_page", "download_executable",
                                       "remote_app_started", "otp_field_visible",
                                       "password_field_visible"])  # fmt: skip
    def test_every_label_has_text_in_both_languages(self, label: str) -> None:
        for language in ("en", "hi"):
            assert reason_view(Reason(t=0.0, label=label, detail=""), language)["text"]

    def test_unknown_labels_fall_back_to_the_label(self) -> None:
        assert reason_view(Reason(t=0.0, label="mystery", detail=""), "en")["text"] == "mystery"


class TestChain:
    def test_no_chain_yet(self) -> None:
        view = chain_view(None, TEMPLATES, "en")
        assert view["seen"] == 0
        assert view["name"] == "No pattern yet"
        assert view["steps"] == []

    def test_steps_in_template_order_with_seen_flags(self) -> None:
        chain = ChainState(
            template="digital_arrest",
            objective=Objective.MONEY_TRANSFER,
            progress=0.59,
            order_score=1.0,
            steps_seen=(("authority", 1.0), ("threat", 5.0), ("control", 9.0)),
        )
        view = chain_view(chain, TEMPLATES, "en")
        assert view["name"] == "Digital arrest"
        assert (view["seen"], view["total"]) == (3, 5)
        assert [(s["label"], s["seen"]) for s in view["steps"]] == [
            ("Authority", True),
            ("Threat", True),
            ("Isolation", True),
            ("Money", False),
            ("Bank page", False),
        ]


class TestEvidenceChips:
    def test_strongest_first_and_capped(self) -> None:
        evidence = {
            SignalKind.AUTHORITY: 0.5,
            SignalKind.THREAT: 0.6,
            SignalKind.ISOLATION: 0.75,
            SignalKind.URGENCY: 0.3,
            SignalKind.MONEY_REQUEST: 0.0,
        }
        chips = evidence_chips(evidence, "en", limit=3)
        assert [(c["label"], c["percent"]) for c in chips] == [
            ("Isolation", 75),
            ("Threat", 60),
            ("Authority", 50),
        ]


class TestHistory:
    def test_bars_take_the_peak_of_each_bucket(self) -> None:
        points = [(float(t), t / 100) for t in range(0, 60)]
        bars = history_bars(points, now=60.0, window_s=60.0, bars=6)
        assert len(bars) == 6
        assert bars[0] == pytest.approx(0.09)
        assert bars[-1] == pytest.approx(0.59)

    def test_empty_buckets_are_zero_and_old_points_are_ignored(self) -> None:
        bars = history_bars([(0.0, 0.9), (55.0, 0.4)], now=60.0, window_s=30.0, bars=3)
        assert bars == [0.0, 0.0, 0.4]

    def test_nothing_yet(self) -> None:
        assert history_bars([], now=0.0, window_s=60.0, bars=4) == [0.0, 0.0, 0.0, 0.0]
