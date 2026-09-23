"""The lexicon: keyword tiers, request vocabulary, negators and suppressions.

``resources/lexicon.yaml`` is validated against a schema, every entry is normalised with
the transcript's own tokenizer, and the vocabulary is compiled into Aho–Corasick automata
once at start-up. A compiled ``Lexicon`` is immutable and safe to share across threads.

Every sentence of Chaukas's own alert copy (``ui/strings.py``) is always added to the
suppressions, so an alert heard back through loopback never counts as caller evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from chaukas.core.errors import ConfigError
from chaukas.core.models import SignalKind, Tier
from chaukas.core.yamlio import read_file_mapping, read_resource_mapping
from chaukas.signals.automaton import TokenAutomaton
from chaukas.signals.normalise import tokenize
from chaukas.ui.strings import alert_sentences

P = TypeVar("P")

_SUFFIXES = ("s", "es", "ed", "d", "ing")
_MIN_INFLECTABLE_LENGTH = 3


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TacticSpec(_Strict):
    terms: list[str] = Field(default_factory=list)
    weak: list[str] = Field(default_factory=list)


class RequestSpec(_Strict):
    verbs: list[str] = Field(min_length=1)
    objects: list[str] = Field(min_length=1)


class NegationSpec(_Strict):
    gap: int = Field(ge=0)
    before: list[str]
    after: list[str]


class LexiconSpec(_Strict):
    """Schema of ``lexicon.yaml``."""

    version: Literal[1]
    tactics: dict[SignalKind, TacticSpec]
    requests: dict[SignalKind, RequestSpec]
    negation: NegationSpec
    suppress: list[str]

    @model_validator(mode="after")
    def _check_kinds(self) -> Self:
        if SignalKind.USER_DIGITS_SPOKEN in self.tactics:
            raise ValueError("user_digits_spoken comes from a rule, not from lexicon terms")
        not_requests = sorted(kind for kind in self.requests if not kind.is_request)
        if not_requests:
            raise ValueError(f"requests may only define request kinds, got {not_requests}")
        return self


@dataclass(frozen=True, slots=True)
class Term:
    """A keyword or phrase after normalisation."""

    kind: SignalKind
    tier: Tier
    text: str


@dataclass(frozen=True, slots=True)
class RequestWord:
    """A request verb or object for one request kind."""

    kind: SignalKind
    role: Literal["verb", "object"]


class Lexicon:
    """Compiled vocabulary: automata ready to scan token lists."""

    __slots__ = (
        "negation_gap",
        "negators_after",
        "negators_before",
        "request_words",
        "suppressions",
        "terms",
    )

    def __init__(self, spec: LexiconSpec) -> None:
        self.terms: TokenAutomaton[Term] = TokenAutomaton()
        for kind, tactic in spec.tactics.items():
            for text in tactic.terms:
                tokens = _tokens(text)
                tier = Tier.STRONG if len(tokens) == 1 else Tier.PHRASE
                _add_inflected(self.terms, tokens, Term(kind, tier, " ".join(tokens)))
            for text in tactic.weak:
                tokens = _tokens(text)
                _add_inflected(self.terms, tokens, Term(kind, Tier.WEAK, " ".join(tokens)))
        self.terms.build()

        self.request_words: TokenAutomaton[RequestWord] = TokenAutomaton()
        for kind, request in spec.requests.items():
            for text in request.verbs:
                _add_inflected(self.request_words, _tokens(text), RequestWord(kind, "verb"))
            for text in request.objects:
                _add_inflected(self.request_words, _tokens(text), RequestWord(kind, "object"))
        self.request_words.build()

        self.suppressions: TokenAutomaton[str] = TokenAutomaton()
        for text in (*spec.suppress, *alert_sentences()):
            tokens = _tokens(text)
            self.suppressions.add(tokens, " ".join(tokens))
        self.suppressions.build()

        self.negators_before: frozenset[str] = _single_tokens(spec.negation.before)
        self.negators_after: frozenset[str] = _single_tokens(spec.negation.after)
        self.negation_gap: int = spec.negation.gap

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Lexicon:
        try:
            spec = LexiconSpec.model_validate(data)
        except ValidationError as exc:
            raise ConfigError(f"invalid lexicon:\n{exc}") from exc
        return cls(spec)

    @classmethod
    def load(cls, path: Path | None = None) -> Lexicon:
        """Load the packaged lexicon, or the file at ``path``."""
        if path is None:
            return cls.from_mapping(read_resource_mapping("lexicon.yaml"))
        return cls.from_mapping(read_file_mapping(path, "lexicon"))


def _tokens(text: str) -> tuple[str, ...]:
    tokens = tuple(tokenize(text))
    if not tokens:
        raise ConfigError(f"lexicon entry {text!r} is empty after normalisation")
    return tokens


def _single_tokens(words: Iterable[str]) -> frozenset[str]:
    result = set()
    for word in words:
        tokens = _tokens(word)
        if len(tokens) != 1:
            raise ConfigError(f"negator {word!r} must be a single word after normalisation")
        result.add(tokens[0])
    return frozenset(result)


def _add_inflected(automaton: TokenAutomaton[P], tokens: tuple[str, ...], payload: P) -> None:
    """Add a pattern plus common English inflections of its last word."""
    automaton.add(tokens, payload)
    last = tokens[-1]
    if not (last.isascii() and last.isalpha() and len(last) >= _MIN_INFLECTABLE_LENGTH):
        return
    forms = {last + suffix for suffix in _SUFFIXES}
    if last.endswith("e"):
        forms.add(last[:-1] + "ing")  # share -> sharing
    for form in sorted(forms):
        automaton.add((*tokens[:-1], form), payload)
