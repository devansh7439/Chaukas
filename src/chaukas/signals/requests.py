"""Request fast path and protective-advice detection.

A request is a verb and an object of the same kind close together: "OTP batao",
"tell me the OTP", "download AnyDesk", "amount transfer karo". Each object is paired with
its nearest verb of the same kind within the window. On a distance tie the non-negated
verb wins, because missing a real request costs more than a spurious warning.

If the chosen verb is negated ("we will never ask for your OTP", "OTP kisi ko mat
batana"), the pair is protective advice, not a request. Its span is still returned so the
extractor can ignore keyword hits inside it.

Cost: one automaton scan, then O(objects * verbs) pairing; both are tiny per segment.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from chaukas.core.models import SignalKind
from chaukas.signals.automaton import Match
from chaukas.signals.lexicon import Lexicon, RequestWord

Span = tuple[int, int]


@dataclass(frozen=True, slots=True)
class RequestHit:
    """A verb–object pair. ``negated`` means protective advice rather than a request."""

    kind: SignalKind
    start: int
    end: int
    negated: bool

    def covers(self, start: int, end: int) -> bool:
        return self.start <= start and end <= self.end


def find_requests(
    tokens: Sequence[str],
    lexicon: Lexicon,
    *,
    window: int,
    excluded: Sequence[Span] = (),
) -> list[RequestHit]:
    """Pair request objects with verbs. Words inside ``excluded`` spans are ignored."""
    verbs: list[Match[RequestWord]] = []
    objects: list[Match[RequestWord]] = []
    for match in lexicon.request_words.find(tokens):
        if inside_any(match.start, match.end, excluded):
            continue
        (verbs if match.payload.role == "verb" else objects).append(match)

    hits: list[RequestHit] = []
    for obj in objects:
        best: tuple[int, bool, Match[RequestWord]] | None = None
        for verb in verbs:
            if verb.payload.kind is not obj.payload.kind:
                continue
            distance = _gap(verb, obj)
            if distance > window:
                continue
            negated = _is_negated(tokens, verb, lexicon)
            if best is None or (distance, negated) < (best[0], best[1]):
                best = (distance, negated, verb)
        if best is not None:
            _, negated, verb = best
            start, end = min(verb.start, obj.start), max(verb.end, obj.end)
            hits.append(RequestHit(obj.payload.kind, start, end, negated))
    return hits


def _gap(a: Match[RequestWord], b: Match[RequestWord]) -> int:
    """Number of tokens strictly between two spans; 0 if they touch or overlap."""
    return max(0, max(a.start, b.start) - min(a.end, b.end))


def _is_negated(tokens: Sequence[str], verb: Match[RequestWord], lexicon: Lexicon) -> bool:
    lo = max(0, verb.start - 1 - lexicon.negation_gap)
    if any(tokens[i] in lexicon.negators_before for i in range(lo, verb.start)):
        return True
    return verb.end < len(tokens) and tokens[verb.end] in lexicon.negators_after


def inside_any(start: int, end: int, spans: Sequence[Span]) -> bool:
    """True if tokens ``[start, end)`` lie entirely inside one of ``spans``."""
    return any(lo <= start and end <= hi for lo, hi in spans)
