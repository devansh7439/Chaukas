"""Classification rules for desktop context: pure functions over names, titles and text.

``resources/context.yaml`` is validated, normalised with the transcript tokenizer and
compiled into token automata once, so every check is a single linear scan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chaukas.core.errors import ConfigError
from chaukas.core.models import ContextKind
from chaukas.core.yamlio import read_file_mapping, read_resource_mapping
from chaukas.signals.automaton import TokenAutomaton
from chaukas.signals.normalise import tokenize

Phrases = list[str]


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _RemoteToolsSpec(_Strict):
    process_names: Phrases = Field(min_length=1)
    product_keywords: Phrases = Field(min_length=1)


class _ScreenSpec(_Strict):
    otp: Phrases = Field(min_length=1)
    password: Phrases = Field(min_length=1)
    transfer: Phrases = Field(min_length=1)
    transfer_min_hits: int = Field(ge=1)


class _RulesSpec(_Strict):
    version: Literal[1]
    banks: Phrases = Field(min_length=1)
    transfer_words: Phrases = Field(min_length=1)
    otp_words: Phrases = Field(min_length=1)
    remote_tools: _RemoteToolsSpec
    executable_extensions: Phrases = Field(min_length=1)
    screen: _ScreenSpec


class _PhraseSet:
    """Whole-word phrase matching over normalised tokens."""

    __slots__ = ("_automaton",)

    def __init__(self, phrases: Iterable[str]) -> None:
        self._automaton: TokenAutomaton[str] = TokenAutomaton()
        for phrase in phrases:
            tokens = tokenize(phrase)
            if not tokens:
                raise ConfigError(f"context phrase {phrase!r} is empty after normalisation")
            self._automaton.add(tokens, " ".join(tokens))
        self._automaton.build()

    def hits(self, tokens: list[str]) -> set[str]:
        return {match.payload for match in self._automaton.find(tokens)}


class ContextRules:
    __slots__ = (
        "_banks",
        "_executables",
        "_otp",
        "_process_names",
        "_products",
        "_screen_otp",
        "_screen_password",
        "_screen_transfer",
        "_transfer",
        "_transfer_min_hits",
    )

    def __init__(self, spec: _RulesSpec) -> None:
        self._banks = _PhraseSet(spec.banks)
        self._transfer = _PhraseSet(spec.transfer_words)
        self._otp = _PhraseSet(spec.otp_words)
        self._process_names = frozenset(name.casefold() for name in spec.remote_tools.process_names)
        self._products = _PhraseSet(spec.remote_tools.product_keywords)
        self._executables = frozenset(ext.casefold() for ext in spec.executable_extensions)
        self._screen_otp = _PhraseSet(spec.screen.otp)
        self._screen_password = _PhraseSet(spec.screen.password)
        self._screen_transfer = _PhraseSet(spec.screen.transfer)
        self._transfer_min_hits = spec.screen.transfer_min_hits

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ContextRules:
        try:
            return cls(_RulesSpec.model_validate(data))
        except ValidationError as exc:
            raise ConfigError(f"invalid context rules:\n{exc}") from exc

    @classmethod
    def load(cls, path: Path | None = None) -> ContextRules:
        if path is None:
            return cls.from_mapping(read_resource_mapping("context.yaml"))
        return cls.from_mapping(read_file_mapping(path, "context rules"))

    def classify_title(self, title: str) -> ContextKind | None:
        """A foreground window title: OTP page, transfer page, bank page, or nothing."""
        tokens = tokenize(title)
        if not self._banks.hits(tokens):
            return None
        if self._otp.hits(tokens):
            return ContextKind.OTP_FIELD_VISIBLE
        if self._transfer.hits(tokens):
            return ContextKind.TRANSFER_PAGE
        return ContextKind.BANK_PAGE

    def is_remote_tool(self, name: str, *, company: str = "", product: str = "") -> bool:
        """A remote-access tool, by process name or by its version-info strings."""
        if name.casefold() in self._process_names:
            return True
        text = " ".join((name.replace("_", " "), company, product))
        return bool(self._products.hits(tokenize(text)))

    def is_executable(self, path: Path) -> bool:
        """A finished download that can run code (partial ``.crdownload`` files are not)."""
        return path.suffix.casefold() in self._executables

    def classify_screen_text(self, text: str) -> ContextKind | None:
        """OCR text of the foreground window."""
        tokens = tokenize(text)
        if self._screen_otp.hits(tokens):
            return ContextKind.OTP_FIELD_VISIBLE
        if self._screen_password.hits(tokens):
            return ContextKind.PASSWORD_FIELD_VISIBLE
        if len(self._screen_transfer.hits(tokens)) >= self._transfer_min_hits:
            return ContextKind.TRANSFER_PAGE
        return None
