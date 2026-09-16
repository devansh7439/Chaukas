"""Signal extractor: one transcript segment in, typed evidence out.

Caller segments produce keyword signals, one per kind (the strongest tier wins), including
request fast-path signals. User segments produce ``user_digits_spoken`` when the user reads
out a code soon after the caller asked for a credential. Keyword hits inside suppressed
phrases ("pin code") or protective advice ("never share your OTP") count for nothing.

The extractor is stateful only for the digit rule: it remembers when the caller recently
asked for a credential, from its own signals or from other detectors via ``observe()``.
``reset()`` wipes that state at session end.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from chaukas.core.config import SignalsConfig
from chaukas.core.models import Segment, Signal, SignalKind, SignalSource, Stream, Tier
from chaukas.core.window import TimeWindow
from chaukas.signals.digits import find_codes
from chaukas.signals.lexicon import Lexicon
from chaukas.signals.normalise import tokenize
from chaukas.signals.requests import RequestHit, Span, find_requests, inside_any

# Protective advice also neutralises isolation phrases inside it: "OTP kisi ko mat batana".
_ALSO_SUPPRESSED_BY_ADVICE: Final = frozenset({SignalKind.ISOLATION})


class SignalExtractor:
    """Stateless per segment except for the digit rule's memory of recent requests."""

    __slots__ = ("_config", "_credential_requests", "_lexicon", "_tier_confidence")

    def __init__(self, lexicon: Lexicon, config: SignalsConfig) -> None:
        self._lexicon = lexicon
        self._config = config
        self._tier_confidence: Mapping[Tier, float] = {
            Tier.WEAK: config.weak,
            Tier.STRONG: config.strong,
            Tier.PHRASE: config.phrase,
            Tier.FAST_PATH: config.fast_path,
        }
        self._credential_requests: TimeWindow[None] = TimeWindow(config.digit_lookback_s)

    def extract(self, segment: Segment) -> list[Signal]:
        """Signals for one segment, in ``SignalKind`` declaration order."""
        tokens = tokenize(segment.text)
        if segment.stream is Stream.USER:
            return self._user_signals(segment, tokens)
        signals = self._caller_signals(segment, tokens)
        for signal in signals:
            self.observe(signal)
        return signals

    def observe(self, signal: Signal) -> None:
        """Remember caller credential requests from any detector, for the digit rule."""
        if (
            signal.kind is SignalKind.CREDENTIAL_REQUEST
            and signal.speaker is Stream.CALLER
            and signal.confidence >= self._config.digit_request_min_confidence
        ):
            self._credential_requests.add(signal.t, None)
            latest = self._credential_requests.latest()
            if latest is not None:
                self._credential_requests.prune(latest[0])

    def reset(self) -> None:
        """Forget everything (session end)."""
        self._credential_requests.clear()

    def _caller_signals(self, segment: Segment, tokens: Sequence[str]) -> list[Signal]:
        suppressed: list[Span] = [(m.start, m.end) for m in self._lexicon.suppressions.find(tokens)]
        requests = find_requests(
            tokens,
            self._lexicon,
            window=self._config.fast_path_window_tokens,
            excluded=suppressed,
        )
        advice = [hit for hit in requests if hit.negated]

        best: dict[SignalKind, Signal] = {}
        for match in self._lexicon.terms.find(tokens):
            kind = match.payload.kind
            if inside_any(match.start, match.end, suppressed):
                continue
            if _neutralised_by_advice(kind, match.start, match.end, advice):
                continue
            self._offer(best, segment, kind, match.payload.tier, tokens[match.start : match.end])
        for hit in requests:
            if not hit.negated:
                self._offer(best, segment, hit.kind, Tier.FAST_PATH, tokens[hit.start : hit.end])
        return [best[kind] for kind in SignalKind if kind in best]

    def _offer(
        self,
        best: dict[SignalKind, Signal],
        segment: Segment,
        kind: SignalKind,
        tier: Tier,
        evidence: Sequence[str],
    ) -> None:
        confidence = self._tier_confidence[tier]
        current = best.get(kind)
        if current is not None and current.confidence >= confidence:
            return
        best[kind] = Signal(
            t=segment.t_start,
            kind=kind,
            source=SignalSource.KEYWORD,
            tier=tier,
            speaker=Stream.CALLER,
            confidence=confidence,
            evidence=" ".join(evidence),
            seg_id=segment.seg_id,
        )

    def _user_signals(self, segment: Segment, tokens: Sequence[str]) -> list[Signal]:
        suppressed_ends = [m.end for m in self._lexicon.suppressions.find(tokens)]
        codes = find_codes(
            tokens,
            min_digits=self._config.digit_min,
            max_digits=self._config.digit_max,
            excluded_ends=suppressed_ends,
        )
        if not codes:
            return []
        window_start = segment.t_start - self._config.digit_lookback_s
        requests = self._credential_requests.with_times()
        if not any(window_start <= t <= segment.t_end for t, _ in requests):
            return []
        return [
            Signal(
                t=segment.t_start,
                kind=SignalKind.USER_DIGITS_SPOKEN,
                source=SignalSource.RULE,
                tier=Tier.RULE,
                speaker=Stream.USER,
                confidence=self._config.digit_confidence,
                evidence=f"user read out a {codes[0].length}-digit code",
                seg_id=segment.seg_id,
            )
        ]


def _neutralised_by_advice(
    kind: SignalKind, start: int, end: int, advice: Sequence[RequestHit]
) -> bool:
    return any(
        hit.covers(start, end) and (kind is hit.kind or kind in _ALSO_SUPPRESSED_BY_ADVICE)
        for hit in advice
    )
