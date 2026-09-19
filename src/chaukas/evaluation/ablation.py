"""The ablation configurations (blueprint 8.5).

    A  keywords only
    B  + LLM tactics
    C  + action gating
    D  + sequence: full Chaukas
    E  D without the LLM, which isolates what the LLM adds

The special rules (pre-disclosure, recovery) and the coercion requirement apply in every
configuration; only the gates and the LLM change.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from chaukas.core.config import ChaukasConfig, ConfigSource, load_config

ABLATIONS: Final[Mapping[str, Mapping[str, bool]]] = MappingProxyType(
    {
        "A": {"use_llm": False, "use_action_gate": False, "use_sequence": False},
        "B": {"use_llm": True, "use_action_gate": False, "use_sequence": False},
        "C": {"use_llm": True, "use_action_gate": True, "use_sequence": False},
        "D": {"use_llm": True, "use_action_gate": True, "use_sequence": True},
        "E": {"use_llm": False, "use_action_gate": True, "use_sequence": True},
    }
)


def config_for(name: str, *overrides: ConfigSource) -> ChaukasConfig:
    """Configuration for ablation ``name``, with ``overrides`` applied underneath it."""
    key = name.strip().upper()
    if key not in ABLATIONS:
        raise KeyError(f"unknown ablation {name!r}; expected one of {sorted(ABLATIONS)}")
    ablation: dict[str, Any] = dict(ABLATIONS[key])
    return load_config(*overrides, {"ablation": ablation})
