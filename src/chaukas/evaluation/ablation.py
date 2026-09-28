"""The ablation configurations (blueprint 8.5).

    A  keywords only (no semantic layer, no LLM, no gates)
    B  + semantic layer + LLM tactics
    C  + action gating
    D  + sequence: full Chaukas
    E  D without the LLM, which isolates what the LLM adds (the default, as in live mode)

The semantic layer is on in B-E, as in live mode, and off in A, so A is keywords only
whether or not the model is downloaded; ``--no-semantic`` switches it off everywhere.

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
        "A": {
            "use_llm": False,
            "use_action_gate": False,
            "use_sequence": False,
            "use_semantic": False,
        },
        "B": {
            "use_llm": True,
            "use_action_gate": False,
            "use_sequence": False,
            "use_semantic": True,
        },
        "C": {
            "use_llm": True,
            "use_action_gate": True,
            "use_sequence": False,
            "use_semantic": True,
        },
        "D": {"use_llm": True, "use_action_gate": True, "use_sequence": True, "use_semantic": True},
        "E": {
            "use_llm": False,
            "use_action_gate": True,
            "use_sequence": True,
            "use_semantic": True,
        },
    }
)


def config_for(name: str, *overrides: ConfigSource) -> ChaukasConfig:
    """Configuration for ablation ``name``, with ``overrides`` applied underneath it."""
    key = name.strip().upper()
    if key not in ABLATIONS:
        raise KeyError(f"unknown ablation {name!r}; expected one of {sorted(ABLATIONS)}")
    ablation: dict[str, Any] = dict(ABLATIONS[key])
    return load_config(*overrides, {"ablation": ablation})
