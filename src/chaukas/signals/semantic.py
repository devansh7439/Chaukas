"""Semantic signals: what a caller line means, for paraphrases the lexicon misses.

The lexicon matches words, so "read me the digits we just sent" (no "OTP", no "code") slips
past it. Here each caller line is embedded with a small multilingual paraphrase model
(``paraphrase-multilingual-MiniLM-L12-v2``, int8 ONNX, ~120 MB, English / Hinglish / Hindi)
and compared with example sentences per signal kind (``resources/intents.yaml``).

A kind fires when the line is close to one of its ``means`` examples (cosine at least
``threshold``) and clearly closer to it than to any of its ``not`` examples (by ``margin``):
look-alikes such as protective advice ("never share your OTP"), because embeddings barely
see negation. The signal is ordinary evidence with its own source and a capped confidence:
a paraphrased request is just enough for the OTP rule, a tactic counts like a keyword
phrase, and every gate of the risk engine still applies. The user's own words are never
semantic evidence.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
import numpy.typing as npt

from chaukas.core.config import SemanticConfig
from chaukas.core.errors import ConfigError
from chaukas.core.models import Segment, Signal, SignalKind, SignalSource, Stream, Tier
from chaukas.core.yamlio import read_resource_mapping

REPO: Final = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION: Final = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
# machine -> (int8 build for it, SHA-256 from the repository)
MODELS: Final[Mapping[str, tuple[str, str]]] = {
    "AMD64": ("onnx/model_quint8_avx2.onnx",
              "98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f"),
    "ARM64": ("onnx/model_qint8_arm64.onnx",
              "783fea82d71a58179b830a4dbd2d58447e640609e98eedf9ffa12622d375a672"),
}  # fmt: skip
TOKENIZER: Final = "tokenizer.json"
_MAX_TOKENS: Final = 128

Vectors = npt.NDArray[np.float32]


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> Vectors:
        """One unit-length row per text."""
        ...


@dataclass(frozen=True)
class Intents:
    means: Mapping[SignalKind, tuple[str, ...]]
    not_: Mapping[SignalKind, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def load(cls) -> Intents:
        data = read_resource_mapping("intents.yaml")
        means: dict[SignalKind, tuple[str, ...]] = {}
        not_: dict[SignalKind, tuple[str, ...]] = {}
        for name, entry in dict(data.get("intents") or {}).items():
            try:
                kind = SignalKind(name)
            except ValueError as exc:
                raise ConfigError(f"intents.yaml: unknown signal kind {name!r}") from exc
            if kind is SignalKind.USER_DIGITS_SPOKEN or not entry.get("means"):
                raise ConfigError(f"intents.yaml: {name} needs `means` examples")
            means[kind] = tuple(str(text) for text in entry["means"])
            not_[kind] = tuple(str(text) for text in entry.get("not") or ())
        return cls(means=means, not_=not_)


class SemanticDetector:
    """Caller line -> signals by meaning. The examples are embedded once, up front."""

    __slots__ = ("_config", "_embedder", "_kinds")

    def __init__(self, embedder: Embedder, intents: Intents, config: SemanticConfig) -> None:
        self._embedder = embedder
        self._config = config
        texts: list[str] = []
        spans: list[tuple[SignalKind, int, int, int]] = []
        for kind, means in intents.means.items():
            negatives = intents.not_.get(kind, ())
            start = len(texts)
            texts.extend(means)
            texts.extend(negatives)
            spans.append((kind, start, start + len(means), start + len(means) + len(negatives)))
        # One text per call, exactly like a live line: the int8 model quantises activations
        # per batch, so in a shared batch every example's vector depended on the others.
        vectors = np.concatenate([embedder.embed([text]) for text in texts]) if texts else (
            np.zeros((0, 0), dtype=np.float32))  # fmt: skip
        self._kinds = [
            (kind, vectors[a:b], tuple(texts[a:b]), vectors[b:c]) for kind, a, b, c in spans
        ]

    def detect(self, segment: Segment) -> list[Signal]:
        text = " ".join(segment.text.split())
        if segment.stream is not Stream.CALLER or not text:
            return []
        line = self._embedder.embed([text])[0]
        signals: list[Signal] = []
        for kind, means, examples, negatives in self._kinds:
            scores = means @ line
            best = int(np.argmax(scores))
            similarity = float(scores[best])
            if similarity < self._config.threshold:
                continue
            if (
                len(negatives)
                and float(np.max(negatives @ line)) > similarity - self._config.margin
            ):
                continue  # it resembles a look-alike (e.g. protective advice) at least as much
            confidence = (self._config.request_confidence if kind.is_request
                          else self._config.tactic_confidence)  # fmt: skip
            signals.append(Signal(
                t=segment.t_start, kind=kind, source=SignalSource.SEMANTIC, tier=Tier.SEMANTIC,
                speaker=Stream.CALLER, confidence=confidence,
                evidence=f'sounds like "{examples[best]}"', seg_id=segment.seg_id,
            ))  # fmt: skip
        return signals


class OnnxEmbedder:
    """The paraphrase model on ONNX Runtime: tokens -> mean-pooled, unit-length vectors."""

    __slots__ = ("_session", "_tokenizer")

    def __init__(self, folder: Path, model_file: str, threads: int = 1) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(folder / TOKENIZER))
        self._tokenizer.enable_truncation(max_length=_MAX_TOKENS)
        pad = self._tokenizer.token_to_id("<pad>")
        self._tokenizer.enable_padding(pad_id=pad if pad is not None else 1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self._session = ort.InferenceSession(str(folder / model_file), options,
                                             providers=["CPUExecutionProvider"])  # fmt: skip

    def embed(self, texts: Sequence[str]) -> Vectors:
        encoded = self._tokenizer.encode_batch(list(texts))
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        hidden = self._session.run(None, {"input_ids": ids, "attention_mask": mask,
                                          "token_type_ids": np.zeros_like(ids)})[0]  # fmt: skip
        weights = mask[..., None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1.0)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        vectors: Vectors = (pooled / np.maximum(norms, 1e-12)).astype(np.float32)
        return vectors


def model_file(machine: str | None = None) -> str | None:
    """The int8 build for this machine, or None if there is none."""
    entry = MODELS.get(machine or platform.machine())
    return entry[0] if entry else None


def find_model() -> Path | None:
    """The downloaded model folder (pinned revision), or None."""
    name = model_file()
    if name is None:
        return None
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        from huggingface_hub import snapshot_download

        folder = Path(snapshot_download(REPO, revision=REVISION, allow_patterns=[TOKENIZER, name],
                                        local_files_only=True))  # fmt: skip
    except Exception:  # not installed, or not in the cache
        return None
    return folder if (folder / TOKENIZER).is_file() and (folder / name).is_file() else None


def download() -> Path:
    """Fetch the model for this machine (pinned revision, SHA-256 checked)."""
    import hashlib

    name = model_file()
    if name is None:
        raise ConfigError(f"no semantic model build for this machine ({platform.machine()})")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import snapshot_download

    folder = Path(snapshot_download(REPO, revision=REVISION, allow_patterns=[TOKENIZER, name]))
    digest = hashlib.sha256((folder / name).read_bytes()).hexdigest()
    expected = MODELS[platform.machine()][1]
    if digest != expected:
        raise ConfigError(f"{name}: SHA-256 is {digest}, expected {expected}")
    return folder


def load_semantic(config: SemanticConfig) -> SemanticDetector | None:
    """The detector, or None when switched off or the model isn't downloaded."""
    if not config.enabled:
        return None
    folder = find_model()
    name = model_file()
    if folder is None or name is None:
        return None
    return SemanticDetector(OnnxEmbedder(folder, name), Intents.load(), config)


def describe(detector: Any) -> str:
    return "on (paraphrase-multilingual-MiniLM-L12-v2)" if detector else "off"
