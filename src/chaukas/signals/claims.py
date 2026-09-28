"""Organisation claims: the caller introduces themselves on behalf of an organisation.

"I am from the refunds team of your electricity company", "This is Rahul calling from the
billing department", "Main insurance company ke claims department se bol rahi hoon". No
known agency is named, so the authority keywords miss it, yet it is exactly the claim that
opens a refund or tech-support scam.

Pattern, inside one clause: a first-person speaker word, then "from" and, within a few
words, an organisation noun (English order); or a speaker word, an organisation noun and
then "se" (Hindi order). The result is only a *weak* authority signal: it satisfies the
remote-banking rule's "claimed to be from an organisation", but is too weak to prime the
OTP rule, fill an attack-chain step or wake the LLM.
"""

from __future__ import annotations

from collections.abc import Sequence

from chaukas.signals.lexicon import Lexicon

Span = tuple[int, int]


def organisation_claim(
    tokens: Sequence[str], lexicon: Lexicon, clause_starts: frozenset[int] = frozenset()
) -> Span | None:
    """The span of the first organisation claim in ``tokens``, or None."""
    spec = lexicon.claims
    for start, token in enumerate(tokens):
        if token not in spec.speakers:
            continue
        end = _clause_end(start, len(tokens), clause_starts, start + 1 + spec.window)
        for i in range(start + 1, end):
            if tokens[i] in spec.from_before:  # English: "... from the billing department"
                after = _clause_end(i, len(tokens), clause_starts, i + 1 + spec.window)
                organisation = next(
                    (j for j in range(i + 1, after) if tokens[j] in spec.organisations), None
                )
                if organisation is not None:
                    return start, organisation + 1
            if tokens[i] in spec.organisations:  # Hindi: "... department se bol rahi hoon"
                for j in range(i + 1, min(end, i + 3)):
                    if tokens[j] in spec.from_after:
                        return start, j + 1
    return None


def _clause_end(start: int, length: int, clause_starts: frozenset[int], limit: int) -> int:
    """The first index after ``start`` that begins a new clause, capped at ``limit``."""
    for i in range(start + 1, min(length, limit)):
        if i in clause_starts:
            return i
    return min(length, limit)
