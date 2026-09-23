"""Configuration: layered, validated once, then immutable.

The packaged ``resources/default.yaml`` is the single source of truth for every tunable.
The models below therefore declare no defaults: a key missing from the YAML is an error,
never a silent fallback. Overrides (a user file, an evaluation config, a test mapping) are
deep-merged on top in order, and the result is validated and frozen.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from chaukas.core.errors import ConfigError
from chaukas.core.models import SignalKind
from chaukas.core.yamlio import read_file_mapping, read_resource_mapping

UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]
Seconds = Annotated[float, Field(gt=0.0)]
PositiveInt = Annotated[int, Field(gt=0)]

ConfigSource = Path | Mapping[str, Any]


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AudioConfig(_Section):
    sample_rate: PositiveInt
    vad_silence_ms: PositiveInt
    max_segment_s: Seconds
    playback_guard_tail_ms: Annotated[int, Field(ge=0)]
    echo_similarity: UnitFloat
    echo_overlap_skip: UnitFloat
    vad_threshold: UnitFloat
    min_speech_ms: PositiveInt
    speech_pad_ms: Annotated[int, Field(ge=0)]
    gap_reset_s: Seconds


class ASRConfig(_Section):
    backend: Literal["onnx", "ctranslate2"]
    model: str = Field(min_length=1)
    language: Literal["auto", "en", "hi"]
    cpu_threads: PositiveInt
    beam_size: PositiveInt
    no_speech_threshold: UnitFloat
    redetect_every: PositiveInt
    merge_max_s: Annotated[float, Field(ge=0.0)]
    hotwords: str


class SignalsConfig(_Section):
    weak: UnitFloat
    strong: UnitFloat
    phrase: UnitFloat
    fast_path: UnitFloat
    fast_path_window_tokens: PositiveInt
    digit_min: PositiveInt
    digit_max: PositiveInt
    digit_lookback_s: Seconds
    digit_request_min_confidence: UnitFloat
    digit_confidence: UnitFloat

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if not self.weak < self.strong < self.phrase < self.fast_path:
            raise ValueError("tier confidences must increase: weak < strong < phrase < fast_path")
        if self.digit_min > self.digit_max:
            raise ValueError("digit_min must not exceed digit_max")
        return self


class LLMConfig(_Section):
    base_url: str
    model: str
    window_s: Seconds
    context_lookback_s: Seconds
    heartbeat_s: Seconds
    heartbeat_min_speech_s: Seconds
    debounce_s: Seconds
    timeout_s: Seconds
    failure_grace_s: Seconds
    max_tokens: PositiveInt
    temperature: Annotated[float, Field(ge=0.0, le=2.0)]
    can_discount: bool
    evidence_min_overlap: UnitFloat


class ThresholdsConfig(_Section):
    notice: UnitFloat
    warning: UnitFloat
    critical: UnitFloat

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if not 0.0 < self.notice < self.warning < self.critical:
            raise ValueError("thresholds must increase: 0 < notice < warning < critical")
        return self


class GatesConfig(_Section):
    addressed_false: UnitFloat
    addressed_true_memory_s: Seconds
    action_none: UnitFloat
    action_other: UnitFloat
    action_match: UnitFloat
    context_lookback_s: Seconds
    sequence_floor: UnitFloat

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        # Every gate is at most 1.0, so the risk score can never exceed pressure (R <= P).
        if not self.action_none <= self.action_other <= self.action_match:
            raise ValueError(
                "action gates must satisfy action_none <= action_other <= action_match"
            )
        return self


class ChainConfig(_Section):
    step_min_confidence: UnitFloat
    required_step_cap: UnitFloat
    order_penalty_threshold: UnitFloat
    order_penalty: UnitFloat
    tie_margin: UnitFloat


class RulesConfig(_Section):
    min_evidence: UnitFloat  # decayed evidence that counts as present
    coercion_floor: UnitFloat  # a confident coercive signal counts while it stays above this
    pre_disclosure_min_confidence: UnitFloat
    hysteresis_margin: UnitFloat
    hysteresis_hold_s: Seconds
    dismissal_s: Seconds


class EngineConfig(_Section):
    weights: dict[SignalKind, UnitFloat]
    evidence_half_life_s: Seconds
    thresholds: ThresholdsConfig
    gates: GatesConfig
    chain: ChainConfig
    rules: RulesConfig

    @model_validator(mode="after")
    def _check_weights(self) -> Self:
        expected = set(SignalKind) - {SignalKind.USER_DIGITS_SPOKEN}
        missing = expected - self.weights.keys()
        extra = self.weights.keys() - expected
        if missing or extra:
            raise ValueError(
                f"weights must cover exactly the pressure tactics; "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        return self


class AblationConfig(_Section):
    use_llm: bool
    use_action_gate: bool
    use_sequence: bool


class UIConfig(_Section):
    capture_exclusion: bool
    language: Literal["en", "hi"]


class PrivacyConfig(_Section):
    transcript_horizon_s: Seconds
    session_idle_end_s: Seconds
    debug_text_logs: bool


class ChaukasConfig(_Section):
    audio: AudioConfig
    asr: ASRConfig
    signals: SignalsConfig
    llm: LLMConfig
    engine: EngineConfig
    ablation: AblationConfig
    ui: UIConfig
    privacy: PrivacyConfig


def load_config(*overrides: ConfigSource) -> ChaukasConfig:
    """Load the packaged defaults, deep-merge ``overrides`` in order, validate and freeze."""
    data: dict[str, Any] = read_resource_mapping("default.yaml")
    for source in overrides:
        override = read_file_mapping(source, "config file") if isinstance(source, Path) else source
        data = deep_merge(data, override)
    try:
        return ChaukasConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration:\n{exc}") from exc


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings; ``override`` wins.

    Non-mapping values, including lists, are replaced rather than merged.
    Neither input is modified.
    """
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged
