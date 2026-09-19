"""Attack-chain templates: schema, validation and loading."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, model_validator

from chaukas.core.errors import ConfigError
from chaukas.core.models import ContextKind, Objective, SignalKind
from chaukas.core.yamlio import read_file_mapping, read_resource_mapping


class _StepSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    signals: list[SignalKind] = Field(default_factory=list)
    events: list[ContextKind] = Field(default_factory=list)
    weight: float = Field(gt=0.0)
    required: bool
    distinctive: bool

    @model_validator(mode="after")
    def _has_evidence(self) -> Self:
        if not self.signals and not self.events:
            raise ValueError(f"step {self.id!r} lists neither signals nor events")
        return self


class _TemplateSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    objective: Objective
    steps: list[_StepSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.objective in (Objective.NONE, Objective.UNCLEAR):
            raise ValueError("a template needs a concrete objective")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate step ids: {ids}")
        if not any(step.required for step in self.steps):
            raise ValueError("a template needs at least one required step")
        return self


class _TemplatesFile(RootModel[dict[str, _TemplateSpec]]):
    pass


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    signals: frozenset[SignalKind]
    events: frozenset[ContextKind]
    weight: float
    required: bool
    distinctive: bool


@dataclass(frozen=True, slots=True)
class ChainTemplate:
    name: str
    objective: Objective
    steps: tuple[Step, ...]

    @property
    def total_weight(self) -> float:
        return sum(step.weight for step in self.steps)


def templates_from_mapping(data: Mapping[str, Any]) -> tuple[ChainTemplate, ...]:
    """Validate and convert a templates mapping, preserving file order."""
    try:
        parsed = _TemplatesFile.model_validate(data).root
    except ValidationError as exc:
        raise ConfigError(f"invalid chain templates:\n{exc}") from exc
    if not parsed:
        raise ConfigError("at least one chain template is required")
    return tuple(
        ChainTemplate(
            name=name,
            objective=spec.objective,
            steps=tuple(
                Step(
                    id=step.id,
                    signals=frozenset(step.signals),
                    events=frozenset(step.events),
                    weight=step.weight,
                    required=step.required,
                    distinctive=step.distinctive,
                )
                for step in spec.steps
            ),
        )
        for name, spec in parsed.items()
    )


def load_templates(path: Path | None = None) -> tuple[ChainTemplate, ...]:
    """Load the packaged templates, or the file at ``path``."""
    if path is None:
        return templates_from_mapping(read_resource_mapping("templates.yaml"))
    return templates_from_mapping(read_file_mapping(path, "chain templates"))
