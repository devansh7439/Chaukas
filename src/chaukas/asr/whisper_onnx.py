"""Whisper on ONNX Runtime: the portable backend (blueprint 6.2).

Runs anywhere ONNX Runtime does, including Windows on ARM64, where CTranslate2 (and so
faster-whisper) has no build. The model is the Hugging Face export of Whisper
(``onnx-community/whisper-<size>``, int8 weights): an encoder, and a decoder with a
key/value cache so each new token costs one short pass.

Decoding is greedy, the same as the CPU backend's ``beam_size=1``:

1. Log-mel features of the segment padded to 30 s (``features.log_mel``), then the encoder.
2. The decoder sees ``<|startoftranscript|>``. Its prediction there gives the language (when
   not known) and the no-speech probability; above ``no_speech_threshold`` the segment is
   dropped, as Whisper would otherwise invent a stock phrase for silence or noise.
3. ``<|lang|> <|transcribe|> <|notimestamps|>`` follow, then one token at a time until
   end-of-text. Special tokens and Whisper's non-speech symbols are never produced.

Two guards against Whisper's habit of looping: at most ``_TOKENS_PER_S`` tokens per second
of audio are generated, and text that compresses too well (the same words again and again)
is dropped. Hindi labelled Urdu is transcribed again as Hindi, as in the CPU backend.

Devices: with ``device="npu"`` the encoder (Whisper's fixed, heaviest cost: one pass over a
30 s window per call) runs on the Snapdragon NPU through ONNX Runtime's QNN execution
provider, from the fp32 encoder in fp16 on the NPU; the decoder stays on the CPU. If the NPU
can't be used (no QNN provider, the fp32 file missing, a session that won't build), the
CPU encoder is used instead and ``runtime.note`` says why: protection never depends on it.
"""

from __future__ import annotations

import json
import logging
import os
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np
import numpy.typing as npt

from chaukas.asr.base import ModelMissingError, Transcript
from chaukas.asr.features import log_mel
from chaukas.audio.convert import TARGET_RATE, Samples

logger = logging.getLogger(__name__)

REPO: Final = "onnx-community/whisper-{size}"
# Pinned: a later push to the repository cannot change what Chaukas runs. Other sizes
# (tiny, base) live in their own repositories with their own revisions.
REVISION: Final = "36050c46d777d46dc4b5f43f6d90574fc38f8732"  # whisper-small
REVISIONS: Final = {"small": REVISION}
ENCODER: Final = "onnx/encoder_model_int8.onnx"
ENCODER_NPU: Final = "onnx/encoder_model.onnx"  # fp32: the NPU runs it in fp16
DECODER: Final = "onnx/decoder_model_merged_int8.onnx"
FILES: Final = (ENCODER, DECODER, "tokenizer.json", "config.json", "generation_config.json")
CPU_PROVIDER: Final = "CPUExecutionProvider"
CPU_PRECISION: Final = "int8 model on the CPU"
NPU_FP16: Final = "fp32 model, run in fp16 on the NPU (QNN HTP)"
NPU_DEFAULT: Final = "fp32 model, the NPU backend's default precision (QNN HTP)"

Device = Literal["cpu", "npu"]


@dataclass(frozen=True, slots=True)
class Runtime:
    """Where Whisper actually runs: the providers ONNX Runtime really bound."""

    requested: Device
    device: Device
    encoder_providers: tuple[str, ...]
    decoder_providers: tuple[str, ...]
    note: str = ""  # why the requested device isn't used; empty if it is
    encoder_precision: str = CPU_PRECISION  # which model file, and how it is computed
    decoder_precision: str = CPU_PRECISION

    @property
    def fallback(self) -> bool:
        return self.device != self.requested


@dataclass(frozen=True, slots=True)
class Timing:
    """Where the last call's time went."""

    encoder_ms: float
    decoder_ms: float


class NpuUnavailableError(RuntimeError):
    """The NPU encoder can't be used here; the reason is the message."""


_RETRY_AS_HINDI: Final = frozenset({"ur"})
_TOKENS_PER_S: Final = 8  # fast speech is about 4; more than this is a loop
_MIN_TOKENS: Final = 16
_MAX_TOKENS: Final = 224  # half Whisper's context, as in the reference
_MAX_COMPRESSION: Final = 2.4  # the reference's threshold for repetitive output
_NO_SPEECH_TOKEN: Final = "<|nocaptions|>"

Logits = npt.NDArray[np.float32]


class WhisperOnnx:
    __slots__ = (
        "_begin_suppress",
        "_decoder",
        "_encoder",
        "_eot",
        "_head_dim",
        "_heads",
        "_language",
        "_languages",
        "_last_timing",
        "_layers",
        "_no_speech",
        "_no_speech_id",
        "_no_timestamps",
        "_runtime",
        "_sot",
        "_suppress",
        "_tokenizer",
        "_transcribe_id",
    )

    def __init__(
        self,
        folder: Path,
        *,
        language: str,
        cpu_threads: int,
        no_speech_threshold: float,
        device: Device = "cpu",
    ) -> None:
        missing = [name for name in FILES if not (folder / name).is_file()]
        if missing:
            raise ModelMissingError(
                f"the ONNX Whisper model is incomplete in {folder} (missing {missing[0]}); "
                "download it with: chaukas setup"
            )
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = _session_options(ort, cpu_threads)
        note = ""
        encoder = None
        encoder_precision = CPU_PRECISION
        if device == "npu":
            try:
                encoder, encoder_precision = _npu_encoder(ort, folder / ENCODER_NPU, cpu_threads)
            except NpuUnavailableError as exc:
                note = f"NPU unavailable, the encoder runs on the CPU: {exc}"
                logger.warning("%s", note)
        on_npu = encoder is not None
        if encoder is None:
            encoder = ort.InferenceSession(str(folder / ENCODER), options,
                                           providers=[CPU_PROVIDER])  # fmt: skip
        self._encoder = encoder
        self._decoder = ort.InferenceSession(str(folder / DECODER), options,
                                             providers=[CPU_PROVIDER])  # fmt: skip
        self._runtime = Runtime(
            requested=device,
            device="npu" if on_npu else "cpu",
            encoder_providers=tuple(self._encoder.get_providers()),
            decoder_providers=tuple(self._decoder.get_providers()),
            note=note,
            encoder_precision=encoder_precision,
        )
        self._last_timing: Timing | None = None
        self._tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))

        config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        self._layers = int(config["decoder_layers"])
        self._heads = int(config["decoder_attention_heads"])
        self._head_dim = int(config["d_model"]) // self._heads
        generation = json.loads((folder / "generation_config.json").read_text(encoding="utf-8"))
        self._sot = int(generation["decoder_start_token_id"])
        self._eot = int(generation["eos_token_id"])
        self._transcribe_id = int(generation["task_to_id"]["transcribe"])
        self._no_timestamps = int(generation["no_timestamps_token_id"])
        self._languages = {int(i): tok[2:-2] for tok, i in generation["lang_to_id"].items()}
        vocab = int(config["vocab_size"])
        suppress = np.zeros(vocab, dtype=bool)
        suppress[[t for t in generation["suppress_tokens"] if 0 <= t < vocab]] = True
        suppress[self._eot + 1 :] = True  # every special token: languages, tasks, timestamps
        self._suppress = suppress
        begin = suppress.copy()
        begin[[t for t in generation["begin_suppress_tokens"] if 0 <= t < vocab]] = True
        self._begin_suppress = begin
        no_speech = self._tokenizer.token_to_id(_NO_SPEECH_TOKEN)
        self._no_speech_id = int(no_speech) if no_speech is not None else None
        self._language = language
        self._no_speech = no_speech_threshold

    @property
    def runtime(self) -> Runtime:
        return self._runtime

    @property
    def last_timing(self) -> Timing | None:
        """Encoder and decoder time of the most recent call (None before the first)."""
        return self._last_timing

    def transcribe(self, samples: Samples, *, language: str | None = None) -> Transcript:
        start = time.perf_counter()
        fixed = language if self._language == "auto" else self._language
        features = log_mel(samples)[None]
        encoder_start = time.perf_counter()
        encoded = self._encoder.run(None, {"input_features": features})[0]
        encoder_ms = (time.perf_counter() - encoder_start) * 1000
        decoder_start = time.perf_counter()
        duration = len(samples) / TARGET_RATE
        text, detected = self._decode(encoded, fixed, duration)
        if fixed is None and detected in _RETRY_AS_HINDI:
            text, detected = self._decode(encoded, "hi", duration)
        decoder_ms = (time.perf_counter() - decoder_start) * 1000
        self._last_timing = Timing(encoder_ms=encoder_ms, decoder_ms=decoder_ms)
        return Transcript(text=text, language=detected, ms=(time.perf_counter() - start) * 1000)

    # ---------------------------------------------------------------- decoding

    def _decode(self, encoded: Any, language: str | None, duration: float) -> tuple[str, str]:
        cache = self._empty_cache()
        logits, cache = self._step([self._sot], encoded, cache, first=True)
        at_sot = logits[0]
        if language is None:
            language = self._languages[max(self._languages, key=lambda i: at_sot[i])]
        no_speech = self._no_speech_id
        if no_speech is not None and _softmax(at_sot)[no_speech] >= self._no_speech:
            return "", language
        language_id = self._tokenizer.token_to_id(f"<|{language}|>")
        if language_id is None:
            raise ValueError(f"Whisper does not know the language {language!r}")
        prompt = [int(language_id), self._transcribe_id, self._no_timestamps]
        logits, cache = self._step(prompt, encoded, cache, first=False)
        tokens: list[int] = []
        limit = min(_MAX_TOKENS, max(_MIN_TOKENS, int(duration * _TOKENS_PER_S)))
        while len(tokens) < limit:
            scores = logits[-1].copy()
            scores[self._begin_suppress if not tokens else self._suppress] = -np.inf
            token = int(np.argmax(scores))
            if token == self._eot:
                break
            tokens.append(token)
            logits, cache = self._step([token], encoded, cache, first=False)
        text = self._tokenizer.decode(tokens, skip_special_tokens=True).strip()
        if text and _compression_ratio(text) > _MAX_COMPRESSION:
            logger.debug("dropped a repetitive transcript (%d characters)", len(text))
            return "", language
        return text, language

    def _empty_cache(self) -> dict[str, Any]:
        empty = np.zeros((1, self._heads, 0, self._head_dim), dtype=np.float32)
        return {
            f"past_key_values.{layer}.{side}.{kind}": empty
            for layer in range(self._layers)
            for side in ("decoder", "encoder")
            for kind in ("key", "value")
        }

    def _step(
        self, tokens: list[int], encoded: Any, cache: dict[str, Any], *, first: bool
    ) -> tuple[Logits, dict[str, Any]]:
        """Feed ``tokens``; return their logits and the cache extended by them."""
        feeds = {
            "input_ids": np.array([tokens], dtype=np.int64),
            "encoder_hidden_states": encoded,
            "use_cache_branch": np.array([not first]),
            **cache,
        }
        outputs = self._decoder.run(None, feeds)
        names = [output.name for output in self._decoder.get_outputs()]
        present = dict(zip(names, outputs, strict=True))
        updated = {}
        for key in cache:
            layer, side, kind = key.split(".")[1:]
            if side == "encoder" and not first:
                updated[key] = cache[key]  # computed once, from the first pass
            else:
                updated[key] = present[f"present.{layer}.{side}.{kind}"]
        logits: Logits = present["logits"][0]
        return logits, updated


def _softmax(scores: Logits) -> npt.NDArray[np.float64]:
    shifted = np.exp(scores.astype(np.float64) - scores.max())
    result: npt.NDArray[np.float64] = shifted / shifted.sum()
    return result


def _compression_ratio(text: str) -> float:
    data = text.encode("utf-8")
    return len(data) / len(zlib.compress(data))


def find_model(size: str) -> Path | None:
    """The downloaded model folder for ``size`` (tiny, base, small), or None."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        from huggingface_hub import snapshot_download

        repo = REPO.format(size=size)
        folder = Path(snapshot_download(repo, allow_patterns=list(FILES),
                                        revision=REVISIONS.get(size),
                                        local_files_only=True))  # fmt: skip
    except Exception:  # not installed, or not in the cache
        return None
    return folder if all((folder / name).is_file() for name in FILES) else None


def download(size: str, device: Device = "cpu") -> Path:
    """Fetch the model into the local cache (the one step that uses the network); for the
    NPU also the fp32 encoder."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import snapshot_download

    if size not in REVISIONS:
        raise ModelMissingError(f"no pinned ONNX Whisper revision for size {size!r}; "
                                f"pinned: {sorted(REVISIONS)}")  # fmt: skip
    files = [*FILES, ENCODER_NPU] if device == "npu" else list(FILES)
    return Path(snapshot_download(REPO.format(size=size), allow_patterns=files,
                                  revision=REVISIONS[size], max_workers=2))  # fmt: skip


def _npu_encoder(ort: Any, path: Path, cpu_threads: int) -> tuple[Any, str]:
    """An encoder session bound to the Snapdragon NPU and the precision it runs in, or
    NpuUnavailableError saying why. fp16 is asked for first; if the backend refuses it, the
    backend's default is used and reported as such.

    ``onnxruntime-qnn`` is a plugin execution provider: its library is registered with ONNX
    Runtime, which then lists the hardware it can drive. Only a device of type NPU is used
    (on other machines the plugin may offer a CPU device that can't run the model), and
    the session is checked afterwards, because ONNX Runtime otherwise falls back to the CPU
    silently.
    """
    try:
        import onnxruntime_qnn as qnn
    except ImportError:
        raise NpuUnavailableError(
            "the QNN plugin (onnxruntime-qnn) is not installed; it runs on Windows on ARM64"
        ) from None
    name = qnn.get_ep_name()
    if not path.is_file():
        raise NpuUnavailableError(
            f"the fp32 encoder is not downloaded ({path.name}); run: chaukas setup --asr-device npu"
        )
    try:
        if not any(device.ep_name == name for device in ort.get_ep_devices()):
            ort.register_execution_provider_library(name, qnn.get_library_path())
        npus = [
            device
            for device in ort.get_ep_devices()
            if device.ep_name == name and device.device.type == ort.OrtHardwareDeviceType.NPU
        ]
    except Exception as exc:  # the plugin library could not be loaded
        raise NpuUnavailableError(f"the QNN plugin could not be loaded: {exc}") from exc
    if not npus:
        raise NpuUnavailableError("the QNN plugin found no Qualcomm NPU on this PC")
    errors = []
    attempts: tuple[tuple[dict[str, str], str], ...] = (
        ({"enable_htp_fp16_precision": "1"}, NPU_FP16),
        ({}, NPU_DEFAULT),
    )
    for provider_options, precision in attempts:
        options = _session_options(ort, cpu_threads)
        options.add_provider_for_devices(npus, provider_options)
        try:
            session = ort.InferenceSession(str(path), sess_options=options)
        except Exception as exc:  # the NPU backend refused the model or an option
            errors.append(str(exc).splitlines()[0][:200])
            continue
        if name in session.get_providers():
            return session, precision
        errors.append("ONNX Runtime fell back to the CPU")
    raise NpuUnavailableError(f"the NPU session could not be created: {'; '.join(errors)}")


def _session_options(ort: Any, cpu_threads: int) -> Any:
    options = ort.SessionOptions()
    options.intra_op_num_threads = cpu_threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3  # errors only
    return options
