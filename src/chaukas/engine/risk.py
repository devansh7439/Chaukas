"""The risk engine (blueprint 6.7): evidence, chains and gates in, a RiskState out.

    P = 1 - prod(1 - w_t * e_t)              pressure: noisy-OR over decayed evidence
    G = addressed gate                       low when the LLM says speech isn't for the user
    A = action gate                          no context / other context / matching context
    S = floor + (1 - floor) * progress       sequence gate from the active chain
    R = clamp(P * G * A * S)                 every gate is <= 1, so R never exceeds P

Levels come from thresholds on R, then:
  * warning and above need coercion: a threat, isolation or surveillance signal that was
    confident when heard and has not faded below ``coercion_floor`` (minutes of speech);
  * critical also needs the hard gate: every required step of the active chain, context
    matching its objective, and speech addressed to the user;
  * nothing escalates before the session's first LLM assessment (with a failure grace);
  * pre-disclosure rule: a confident caller credential request is critical at once if
    authority or coercion was heard within ``priming_window_s`` of speech before it, and
    a warning otherwise. An LLM verdict
    of "not addressed to the user" can lower it to a warning but never silence it;
  * recovery rule: a code read out after a pre-disclosure alert is critical_recovery.
  * call presence: when Windows shows that no app holds the microphone, no call is
    happening and the loopback is media (a film, the news), so the level stops at a notice;
    an unknown call state changes nothing;
  * A critical or critical_recovery raised by these rules holds until the session ends:
    the request's evidence decays, but a caller who stalls after asking for the OTP is
    still waiting for it.
Hysteresis and dismissal then decide what is shown.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

from chaukas.core.config import AblationConfig, ChaukasConfig, EngineConfig, LLMConfig
from chaukas.core.models import (
    ChainState,
    ContextEvent,
    ContextKind,
    Level,
    LLMAssessment,
    Objective,
    Reason,
    RiskComponents,
    RiskState,
    Segment,
    Signal,
    SignalKind,
    Stream,
    Tier,
)
from chaukas.core.window import TimeWindow
from chaukas.engine.activity import ActivityClock
from chaukas.engine.chains import ChainTracker
from chaukas.engine.evidence import EvidenceStore
from chaukas.engine.levels import LevelController
from chaukas.engine.templates import ChainTemplate, Step, load_templates

_DISCOUNTABLE: Final = frozenset({SignalKind.AUTHORITY, SignalKind.THREAT, SignalKind.URGENCY})
_DISCOUNT_FACTOR: Final = 0.5
_LLM_TRIGGER_TIERS: Final = frozenset({Tier.STRONG, Tier.PHRASE, Tier.FAST_PATH, Tier.LLM})
_COERCIVE: Final = tuple(kind for kind in SignalKind if kind.is_coercive)
_BANKING: Final = frozenset({ContextKind.BANK_PAGE, ContextKind.TRANSFER_PAGE})


class RiskEngine:
    """Single-threaded and deterministic: drive it with events, query it with ``evaluate``."""

    def __init__(
        self,
        engine: EngineConfig,
        llm: LLMConfig,
        ablation: AblationConfig,
        templates: Sequence[ChainTemplate],
    ) -> None:
        self._config = engine
        self._llm = llm
        self._ablation = ablation
        self._clock = ActivityClock()
        self._evidence = EvidenceStore(engine.evidence_half_life_s, self._clock)
        self._chains = ChainTracker(templates, engine.chain)
        self._levels = LevelController(engine.thresholds, engine.rules)
        self._context: TimeWindow[ContextEvent] = TimeWindow(engine.gates.context_lookback_s)
        self._addressed_true: TimeWindow[None] = TimeWindow(engine.gates.addressed_true_memory_s)
        self._latest: LLMAssessment | None = None
        self._discounted: set[tuple[int, SignalKind]] = set()
        self._first_trigger_t: float | None = None
        self._held = Level.QUIET  # raised by the credential rules; held until session end
        self._held_signals: tuple[Signal, ...] = ()  # what raised the hold, for the trace
        self._call_active: bool | None = None  # None: unknown, so no call-presence cap
        self._last_call_t: float | None = None  # when a call app last held the microphone
        self._changes = 0  # new chain steps or context events; invalidates dismissals

    @classmethod
    def from_config(
        cls, config: ChaukasConfig, templates: Sequence[ChainTemplate] | None = None
    ) -> RiskEngine:
        chosen = load_templates() if templates is None else templates
        return cls(config.engine, config.llm, config.ablation, chosen)

    # ----------------------------------------------------------------- inputs

    def on_segment(self, segment: Segment) -> None:
        """Speech happened: advances call time, which drives evidence decay."""
        self._clock.add(segment.t_start, segment.t_end)

    def on_signal(self, signal: Signal) -> None:
        if not _counts_as_evidence(signal):
            return
        self._evidence.add(signal)
        if self._first_trigger_t is None and signal.tier in _LLM_TRIGGER_TIERS:
            self._first_trigger_t = signal.t
        self._expire_chain_steps(signal.t)
        if self._chains.observe_signal(signal):
            self._changes += 1

    def on_context(self, event: ContextEvent) -> None:
        if event.kind in (ContextKind.CALL_ACTIVE, ContextKind.NO_CALL):
            self._call_active = event.kind is ContextKind.CALL_ACTIVE
            if self._call_active or self._last_call_t is not None:
                self._last_call_t = event.t  # a call now, or the moment it went quiet
            return
        if event.objective is None:
            return
        self._context.add(event.t, event)
        self._expire_chain_steps(event.t)
        self._chains.observe_context(event)
        self._changes += 1

    def on_assessment(self, assessment: LLMAssessment) -> None:
        if not self._ablation.use_llm:
            return
        if self._latest is None or assessment.t >= self._latest.t:
            self._latest = assessment
        if assessment.addressed_to_user:
            self._addressed_true.add(assessment.t, None)
        if self._llm.can_discount:
            self._discount_unconfirmed(assessment)

    def dismiss(self, now: float) -> None:
        """The user pressed "I understand, continue" on the current alert."""
        self._levels.dismiss(now, self._changes)

    def reset(self) -> None:
        """Session end: forget everything."""
        self._clock.reset()
        self._evidence.reset()
        self._chains.reset()
        self._levels.reset()
        self._context.clear()
        self._addressed_true.clear()
        self._latest = None
        self._discounted.clear()
        self._first_trigger_t = None
        self._held = Level.QUIET
        self._held_signals = ()
        self._call_active = None
        self._last_call_t = None
        self._changes = 0

    # ------------------------------------------------------------- evaluation

    def evaluate(self, now: float) -> RiskState:
        self._context.prune(now)
        self._addressed_true.prune(now)
        self._evidence.prune(now)

        weights = self._config.weights
        evidence = {kind: self._evidence.level(kind, now) for kind in SignalKind}
        pressure = 1.0 - math.prod(1.0 - w * evidence[kind] for kind, w in weights.items())
        self._expire_chain_steps(now)
        hint = self._objective_hint()
        active = self._chains.active(hint)
        addressed, is_addressed = self._addressed_gate()
        action, context_matches = self._action_gate(active)
        sequence = self._sequence_gate(active)
        score = min(1.0, max(0.0, pressure * addressed * action * sequence))
        rules = self._config.rules
        coercion = any(
            self._evidence.level(kind, now, min_confidence=rules.min_evidence)
            >= rules.coercion_floor
            for kind in _COERCIVE
        )

        raw = self._threshold_level(score, active, context_matches, is_addressed, coercion)
        rule = "threshold"
        if self._awaiting_llm(now):
            raw, rule = Level.QUIET, "awaiting_llm"
        raw, rule, rule_objective = self._apply_rules(now, raw, rule, evidence, is_addressed)
        if raw > Level.NOTICE and self._no_call(now):
            # No app holds the microphone: the loopback is a video or the news, not a call.
            raw, rule = Level.NOTICE, "no_call"
        level = self._levels.update(now, raw, score)

        return RiskState(
            t=now,
            score=score,
            level=level,
            objective=self._objective(level, active, hint, rule_objective),
            components=RiskComponents(
                pressure=min(1.0, max(0.0, pressure)),
                addressed=addressed,
                action=action,
                sequence=sequence,
            ),
            chain=active,
            coercion=coercion,
            llm_assessed=self._latest is not None,
            dismissed=self._levels.is_dismissed(now, self._changes),
            reasons=self._reasons(now, evidence, active),
            evidence=tuple((kind, value) for kind, value in evidence.items() if value > 0.0),
            rule=rule,
        )

    # ---------------------------------------------------------------- helpers

    def _discount_unconfirmed(self, assessment: LLMAssessment) -> None:
        for kind in _DISCOUNTABLE - assessment.listed_kinds:
            fresh = {
                seg_id
                for seg_id in assessment.covered_seg_ids
                if (seg_id, kind) not in self._discounted
            }
            if fresh:
                self._evidence.discount((kind,), fresh, _DISCOUNT_FACTOR)
                self._discounted.update((seg_id, kind) for seg_id in fresh)

    def _objective_hint(self) -> Objective | None:
        if not self._ablation.use_llm or self._latest is None:
            return None
        objective = self._latest.suspected_objective
        return None if objective in (Objective.NONE, Objective.UNCLEAR) else objective

    def _addressed_gate(self) -> tuple[float, bool]:
        latest = self._latest
        if not self._ablation.use_llm or latest is None or latest.addressed_to_user:
            return 1.0, True
        if self._addressed_true:  # a recent assessment said the speech was for the user
            return 1.0, True
        return self._config.gates.addressed_false, False

    def _action_gate(self, active: ChainState | None) -> tuple[float, bool]:
        if not self._ablation.use_action_gate:
            return 1.0, False
        gates = self._config.gates
        if not self._context:
            return gates.action_none, False
        if active is not None and any(
            event.objective is active.objective for event in self._context
        ):
            return gates.action_match, True
        return gates.action_other, False

    def _sequence_gate(self, active: ChainState | None) -> float:
        if not self._ablation.use_sequence:
            return 1.0
        floor = self._config.gates.sequence_floor
        progress = active.progress if active is not None else 0.0
        return floor + (1.0 - floor) * progress

    def _threshold_level(
        self,
        score: float,
        active: ChainState | None,
        context_matches: bool,
        is_addressed: bool,
        coercion: bool,
    ) -> Level:
        thresholds = self._config.thresholds
        if score >= thresholds.critical:
            gate = coercion and is_addressed
            if self._ablation.use_sequence:
                gate = gate and active is not None and active.required_seen
            if self._ablation.use_action_gate:
                gate = gate and context_matches
            level = Level.CRITICAL if gate else Level.WARNING
        elif score >= thresholds.warning:
            level = Level.WARNING
        elif score >= thresholds.notice:
            level = Level.NOTICE
        else:
            level = Level.QUIET
        if level >= Level.WARNING and not coercion:
            level = Level.NOTICE
        return level

    def _awaiting_llm(self, now: float) -> bool:
        if not self._ablation.use_llm or self._latest is not None:
            return False
        first = self._first_trigger_t
        return first is None or now - first < self._llm.failure_grace_s

    def _apply_rules(
        self,
        now: float,
        level: Level,
        rule: str,
        evidence: dict[SignalKind, float],
        is_addressed: bool,
    ) -> tuple[Level, str, Objective | None]:
        rules = self._config.rules
        rule_objective: Objective | None = None
        raised_hold = ""

        def at_least(target: Level, name: str) -> None:
            nonlocal level, rule
            if target > level:
                level, rule = target, name

        credential = evidence[SignalKind.CREDENTIAL_REQUEST]
        if credential >= rules.pre_disclosure_min_confidence:
            rule_objective = Objective.CREDENTIAL_DISCLOSURE
            prime = self._prime(now)
            # An LLM verdict of "not addressed to the user" can be induced by the caller
            # ("this is a recorded announcement"), so it may lower this alert to a warning,
            # never remove it: the warning still says never to share an OTP.
            if prime is not None and is_addressed:
                if self._held < Level.CRITICAL:
                    request = self._evidence.strongest(SignalKind.CREDENTIAL_REQUEST, now)
                    self._held_signals = tuple(s for s in (prime, request) if s is not None)
                self._held = max(self._held, Level.CRITICAL)
                raised_hold = "pre_disclosure_primed"
            else:
                at_least(Level.WARNING, "pre_disclosure")
        if evidence[SignalKind.USER_DIGITS_SPOKEN] >= rules.min_evidence:
            rule_objective = Objective.CREDENTIAL_DISCLOSURE
            if self._held >= Level.CRITICAL:
                if self._held is not Level.CRITICAL_RECOVERY:
                    digits = self._evidence.strongest(SignalKind.USER_DIGITS_SPOKEN, now)
                    self._held_signals += (digits,) if digits is not None else ()
                self._held = Level.CRITICAL_RECOVERY
                raised_hold = "recovery"
            else:
                at_least(Level.WARNING, "digits")
        if self._remote_banking():
            at_least(Level.WARNING, "remote_banking")
            rule_objective = rule_objective or Objective.REMOTE_CONTROL
        if self._held > level:
            level, rule = self._held, raised_hold or "held"
            rule_objective = Objective.CREDENTIAL_DISCLOSURE
        return level, rule, rule_objective

    def _no_call(self, now: float) -> bool:
        """Windows shows no app holding the microphone, and none has for
        ``no_call_grace_s``: some call apps release it while the person is muted, so a
        recent call still counts as a call."""
        if self._call_active is not False:
            return False
        last = self._last_call_t
        return last is None or now - last > self._config.rules.no_call_grace_s

    def _prime(self, now: float) -> Signal | None:
        """The latest authority or coercion signal heard confidently within the last
        ``priming_window_s`` of speech, or None. Loopback hears all PC audio, so a session
        can span a news clip and, much later, an unrelated call: a "CBI" from then must not
        make today's OTP request critical. Speech time, not wall time, so a long silent hold
        in a digital-arrest call does not expire it."""
        min_evidence = self._config.rules.min_evidence
        heard = [
            signal
            for kind in (SignalKind.AUTHORITY, *_COERCIVE)
            if (signal := self._evidence.latest(kind, min_confidence=min_evidence)) is not None
            and self._recent(signal.t, now)
        ]
        return max(heard, key=lambda signal: signal.t, default=None)

    def _expire_chain_steps(self, now: float) -> None:
        """Forget chain steps not seen within ``step_memory_s`` of speech before ``now``,
        so a new sighting of an old step starts it afresh."""
        memory = self._config.chain.step_memory_s
        self._chains.expire(lambda t: not self._within(t, now, memory))

    def _recent(self, t: float, now: float) -> bool:
        """``t`` lies within ``priming_window_s`` of speech before ``now``."""
        return self._within(t, now, self._config.rules.priming_window_s)

    def _within(self, t: float, now: float, speech_s: float) -> bool:
        """At most ``speech_s`` seconds of speech lie between ``t`` and ``now``."""
        return self._clock.call_time(now) - self._clock.call_time(t) <= speech_s

    def _remote_banking(self) -> bool:
        """The causal order of a remote-control scam: the caller claims to be from an
        organisation (even a weak "customer care"), *then* a remote-control app starts,
        and the bank opens within ``remote_banking_window_s`` of that start.

        The tech-support and refund scam needs no threats, so the coercion rule alone
        would stop it at a notice. Family remote help makes no organisation claim, and a
        remote session the user started before the claim (for their own reasons) does
        not count. The claim may come minutes before the install request.
        """
        rules = self._config.rules
        if not rules.remote_banking_warning:
            return False
        claimed = self._evidence.first_seen(SignalKind.AUTHORITY)
        if claimed is None:
            return False
        remote_starts = [e.t for e in self._context
                         if e.kind is ContextKind.REMOTE_APP_STARTED and e.t > claimed]  # fmt: skip
        banking = [e.t for e in self._context if e.kind in _BANKING]
        window = rules.remote_banking_window_s
        return any(start <= bank <= start + window for start in remote_starts for bank in banking)

    def _objective(
        self,
        level: Level,
        active: ChainState | None,
        hint: Objective | None,
        rule_objective: Objective | None,
    ) -> Objective:
        if rule_objective is not None:
            return rule_objective
        if active is not None and active.distinctive_seen:
            return active.objective
        if hint is not None:
            return hint
        return Objective.UNCLEAR if level > Level.QUIET else Objective.NONE

    def _reasons(
        self, now: float, evidence: dict[SignalKind, float], active: ChainState | None
    ) -> tuple[Reason, ...]:
        """The decision trace: every confident signal heard within ``priming_window_s`` of
        speech, the signals behind a held alert, and the context events in the look-back.

        Evidence fades for scoring, but the Why panel keeps explaining it: a strong keyword
        starts exactly at ``min_evidence`` and would otherwise vanish within seconds. What
        is older than the window is left out, as it no longer takes part in any rule; a
        held alert keeps quoting what raised it."""
        min_evidence = self._config.rules.min_evidence
        chosen: dict[SignalKind, Signal] = {}
        for kind in SignalKind:
            if self._evidence.peak(kind) < min_evidence:
                continue
            # the signal that met the bar, not whatever is strongest now (a weak "officer"
            # heard later must not stand in for the "CBI" that justified the alert)
            signal = self._evidence.explanation(kind, now, min_confidence=min_evidence)
            if signal is not None and self._recent(signal.t, now):
                chosen[kind] = signal
        if self._held > Level.QUIET:
            for signal in self._held_signals:
                chosen.setdefault(signal.kind, signal)

        steps = self._seen_steps(active)
        weights = self._config.weights
        reasons = [
            Reason(
                t=signal.t,
                label=kind.value,
                detail=signal.evidence,
                source=signal.source.value,
                confidence=signal.confidence,
                current=evidence[kind],
                contribution=weights.get(kind, 0.0) * evidence[kind],
                chain_step=next((s.id for s in steps if kind in s.signals), None),
            )
            for kind, signal in chosen.items()
        ]
        reasons.extend(
            Reason(
                t=event.t,
                label=event.kind.value,
                detail=event.detail,
                source="screen",
                chain_step=next((s.id for s in steps if event.kind in s.events), None),
            )
            for event in self._context
        )
        return tuple(sorted(reasons, key=lambda reason: reason.t))

    def _seen_steps(self, active: ChainState | None) -> list[Step]:
        """The active chain's steps that have been seen, in template order."""
        if active is None:
            return []
        template = next((t for t in self._chains.templates if t.name == active.template), None)
        seen = {step_id for step_id, _ in active.steps_seen}
        return [step for step in (template.steps if template else ()) if step.id in seen]


def _counts_as_evidence(signal: Signal) -> bool:
    """Caller speech is evidence; from the user, only the digits rule is."""
    if signal.kind is SignalKind.USER_DIGITS_SPOKEN:
        return signal.speaker is Stream.USER
    return signal.speaker is Stream.CALLER
