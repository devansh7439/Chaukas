"""Request fast path and protective-advice detection.

A request is a verb and an object of the same kind close together: "OTP batao",
"tell me the OTP", "download AnyDesk", "amount transfer karo". Each object is paired with
its nearest verb of the same kind within the window. On a distance tie the non-negated
verb wins, because missing a real request costs more than a spurious warning.

If the chosen verb is negated ("we will never ask for your OTP", "OTP kisi ko mat
batana"), the pair is protective advice, not a request. Its span is still returned so the
extractor can ignore keyword hits inside it, and it stretches over every object in a list
("OTP ya PIN ... mat bataiye").

The caller is untrusted, so advice must not be usable as cover: if a non-negated verb of
the same kind in the window is aimed at the speaker ("kisi ko mat batana, sirf *mujhe*
batao", "never share it with anyone, just read it out *to me*"), the pair is a request and
no advice span is returned (the "don't tell anyone" part is then isolation, not advice).

For the same reason the caller must not be able to forge advice: a negator counts only
inside the verb's clause, with at most filler words ("never *ever* share") in between. So
"No, read out the OTP", "Don't panic, share the OTP" and "don't worry send the OTP" stay
requests: what is negated there is the reassurance, not the request.

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
    clause_starts: frozenset[int] = frozenset(),
) -> list[RequestHit]:
    """Pair request objects with verbs. Words inside ``excluded`` spans are ignored;
    ``clause_starts`` (from ``tokenize_clauses``) keeps negation inside its clause."""
    verbs: list[Match[RequestWord]] = []
    objects: list[Match[RequestWord]] = []
    for match in lexicon.request_words.find(tokens):
        if inside_any(match.start, match.end, excluded):
            continue
        (verbs if match.payload.role == "verb" else objects).append(match)

    hits: list[RequestHit] = []
    for obj in objects:
        candidates = [
            (_gap(verb, obj), _is_negated(tokens, verb, lexicon, clause_starts), verb)
            for verb in verbs
            if verb.payload.kind is obj.payload.kind and _gap(verb, obj) <= window
        ]
        if not candidates:
            continue
        _, negated, verb = min(candidates, key=lambda c: (c[0], c[1]))
        if negated:
            redirected = [
                c for c in candidates if not c[1] and _aimed_at_speaker(tokens, c[2], lexicon)
            ]
            if redirected:
                negated, verb = False, min(redirected, key=lambda c: c[0])[2]
        start, end = min(verb.start, obj.start), max(verb.end, obj.end)
        if negated:
            start = _extend_over_list(tokens, objects, obj.payload.kind, start, lexicon)
        hits.append(RequestHit(obj.payload.kind, start, end, negated))
    return hits


def _aimed_at_speaker(tokens: Sequence[str], verb: Match[RequestWord], lexicon: Lexicon) -> bool:
    """A first-person recipient ("mujhe", "me") near the verb: "mujhe batao", "tell me",
    "read it out to me"."""
    lo, hi = max(0, verb.start - 3), min(len(tokens), verb.end + 4)
    return any(tokens[i] in lexicon.redirect_recipients for i in range(lo, hi))


def _extend_over_list(
    tokens: Sequence[str],
    objects: Sequence[Match[RequestWord]],
    kind: SignalKind,
    start: int,
    lexicon: Lexicon,
) -> int:
    """Move ``start`` back over objects joined by a connector: "OTP ya PIN ... mat batana"."""
    starts_by_end = {o.end: o.start for o in objects if o.payload.kind is kind}
    while start >= 2 and tokens[start - 1] in lexicon.negation_connectors:
        previous = starts_by_end.get(start - 1)
        if previous is None:
            break
        start = previous
    return start


def _gap(a: Match[RequestWord], b: Match[RequestWord]) -> int:
    """Number of tokens strictly between two spans; 0 if they touch or overlap."""
    return max(0, max(a.start, b.start) - min(a.end, b.end))


def _is_negated(
    tokens: Sequence[str],
    verb: Match[RequestWord],
    lexicon: Lexicon,
    clause_starts: frozenset[int],
) -> bool:
    if verb.start not in clause_starts:
        for gap in range(lexicon.negation_gap + 1):
            i = verb.start - 1 - gap
            if i < 0:
                break
            if tokens[i] in lexicon.negators_before:
                return True
            if tokens[i] not in lexicon.negation_fillers:
                break  # "do not worry send": the negator belongs to another word
    return (
        verb.end < len(tokens)
        and verb.end not in clause_starts
        and tokens[verb.end] in lexicon.negators_after
    )


def inside_any(start: int, end: int, spans: Sequence[Span]) -> bool:
    """True if tokens ``[start, end)`` lie entirely inside one of ``spans``."""
    return any(lo <= start and end <= hi for lo, hi in spans)
