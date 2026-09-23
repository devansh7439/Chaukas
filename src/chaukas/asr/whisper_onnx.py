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
"""

from __future__ import annotations

import json
import logging
import os
import time
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from chaukas.asr.base import ModelMissingError, Transcript
from chaukas.asr.features import log_mel
from chaukas.audio.convert import TARGET_RATE, Samples

logger = logging.getLogger(__name__)

REPO: Final = "onnx-community/whisper-{size}"
ENCODER: Final = "onnx/encoder_model_int8.onnx"
DECODER: Final = "onnx/decoder_model_merged_int8.onnx"
FILES: Final = (ENCODER, DECODER, "tokenizer.json", "config.json", "generation_config.json")

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
        "_layers",
        "_no_speech",
        "_no_speech_id",
        "_no_timestamps",
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
        providers: Sequence[str] = ("CPUExecutionProvider",),
    ) -> None:
        missing = [name for name in FILES if not (folder / name).is_file()]
        if missing:
            raise ModelMissingError(
                f"the ONNX Whisper model is incomplete in {folder} (missing {missing[0]}); "
                "download it with: chaukas setup"
            )
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = cpu_threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3  # errors only
        self._encoder = ort.InferenceSession(str(folder / ENCODER), options, providers=providers)
        self._decoder = ort.InferenceSession(str(folder / DECODER), options, providers=providers)
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

    def transcribe(self, samples: Samples, *, language: str | None = None) -> Transcript:
        start = time.perf_counter()
        fixed = language if self._language == "auto" else self._language
        encoded = self._encoder.run(None, {"input_features": log_mel(samples)[None]})[0]
        duration = len(samples) / TARGET_RATE
        text, detected = self._decode(encoded, fixed, duration)
        if fixed is None and detected in _RETRY_AS_HINDI:
            text, detected = self._decode(encoded, "hi", duration)
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
            logger.debug("dropped a repetitive transcript: %r", text[:80])
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

        folder = Path(snapshot_download(REPO.format(size=size), allow_patterns=list(FILES),
                                        local_files_only=True))  # fmt: skip
    except Exception:  # not installed, or not in the cache
        return None
    return folder if all((folder / name).is_file() for name in FILES) else None


def download(size: str) -> Path:
    """Fetch the model into the local cache (the one step that uses the network)."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(REPO.format(size=size), allow_patterns=list(FILES),
                                  max_workers=2))  # fmt: skip
