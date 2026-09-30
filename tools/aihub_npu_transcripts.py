"""Whisper's encoder on a real Snapdragon NPU, end to end: spoken scam calls -> NPU -> alerts.

Profiling (``aihub_profile.py``) shows the encoder is fast on the NPU. This shows it is
also *right*: every line of the English cases of sets D and E is spoken by a Windows voice
(as in ``audio_eval.py``), turned into Whisper's log-mel features here, and sent to a real
Snapdragon device in Qualcomm AI Hub, where the fp32 encoder Chaukas uses for the NPU runs
on the Hexagon NPU (ONNX Runtime, QNN provider). The encoder output comes back, is decoded
here by Chaukas's own decoder, and every case is scored twice: with the NPU transcripts,
and with this PC's CPU transcripts. The encoder outputs are also compared number by number
with the same fp32 model run on this PC's CPU.

Uploaded: the public encoder weights and the log-mel features of synthetic speech (no
real voice, no call). Nothing else leaves the PC.

    uv run --with qai-hub --with winrt-Windows.Media.SpeechSynthesis ^
        --with winrt-Windows.Storage.Streams --with winrt-Windows.Foundation ^
        --with winrt-Windows.Foundation.Collections ^
        python tools/aihub_npu_transcripts.py eval/redteam eval/remote
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aihub_profile import INPUT_SPECS, OUT_DIR, _download_encoder, _hub
from audio_eval import VOICES, _norm, _speak

from chaukas.asr.benchmark import load_wav
from chaukas.asr.features import log_mel
from chaukas.asr.loader import load_transcriber
from chaukas.audio.convert import TARGET_RATE
from chaukas.evaluation.ablation import config_for
from chaukas.evaluation.cases import Case, load_cases
from chaukas.evaluation.metrics import score_case, summarise
from chaukas.evaluation.report import format_summary
from chaukas.evaluation.runner import run_case
from chaukas.signals.lexicon import Lexicon
from chaukas.signals.semantic import load_semantic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", type=Path, nargs="+")
    parser.add_argument("--device", default="Snapdragon X Elite CRD")
    args = parser.parse_args()

    config = config_for("E")
    lexicon = Lexicon.load()
    semantic = load_semantic(config.signals.semantic)
    whisper: Any = load_transcriber(config.asr)  # this PC's CPU runtime (int8)
    cases = [c for folder in args.folders for c in load_cases(folder) if c.language == "english"]

    # 1. Speak every line; features for the NPU; CPU transcripts here.
    lines: list[tuple[int, int, float, Any, str]] = []  # case, line, seconds, features, cpu text
    with tempfile.TemporaryDirectory() as folder:
        for c, case in enumerate(cases):
            for i, line in enumerate(case.lines):
                wav = Path(folder) / f"{case.case_id}-{i}.wav"
                asyncio.run(_speak(line.text, VOICES[line.stream], wav))
                samples = load_wav(wav)
                cpu_text = whisper.transcribe(samples).text.strip()
                features = log_mel(samples)[None].astype(np.float32)
                lines.append((c, i, len(samples) / TARGET_RATE, features, cpu_text))
    print(f"{len(cases)} cases, {len(lines)} spoken lines")

    # 2. The encoder on the device's NPU.
    hub = _hub()
    device = hub.Device(args.device)
    encoder = _download_encoder()
    print(f"Compiling the fp32 encoder for {args.device}... several minutes")
    compile_job = hub.submit_compile_job(
        model=str(encoder), device=device, name="chaukas-whisper-small-encoder",
        input_specs=INPUT_SPECS, options="--target_runtime onnx",
    )  # fmt: skip
    print(f"  {compile_job.url}")
    target = compile_job.get_target_model()
    if target is None:
        print("Compilation failed; see the job page above.", file=sys.stderr)
        return 1
    print(f"Running {len(lines)} encoder passes on the device's NPU...")
    inference_job = hub.submit_inference_job(
        model=target, device=device, name="chaukas-whisper-npu-transcripts",
        inputs={"input_features": [features for *_, features, _ in lines]},
    )  # fmt: skip
    print(f"  {inference_job.url}")
    outputs = inference_job.download_output_data()
    if outputs is None:
        print("The inference job failed; see the job page above.", file=sys.stderr)
        return 1
    npu_encoded = next(iter(outputs.values()))

    # 3. The same fp32 model on this PC's CPU, for a number-by-number comparison.
    import onnxruntime as ort

    fp32 = ort.InferenceSession(str(encoder), providers=["CPUExecutionProvider"])
    cosines, max_abs = [], []
    npu_text: dict[tuple[int, int], str] = {}
    for (c, i, seconds, features, _), encoded in zip(lines, npu_encoded, strict=True):
        reference = fp32.run(None, {"input_features": features})[0]
        a, b = encoded.ravel().astype(np.float64), reference.ravel().astype(np.float64)
        cosines.append(float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b))))
        max_abs.append(float(np.max(np.abs(a - b))))
        npu_text[(c, i)] = whisper.decode_encoded(encoded.astype(np.float32), seconds)[0].strip()

    # 4. Score every case with the NPU transcripts and with the CPU transcripts.
    cpu_text = {(c, i): text for c, i, _, _, text in lines}
    rows, npu_outcomes, cpu_outcomes, differing = [], [], [], []
    for c, case in enumerate(cases):

        def heard(texts: dict[tuple[int, int], str], c: int = c, case: Case = case) -> Case:
            new = tuple(dataclasses.replace(line, text=texts[(c, i)])
                        for i, line in enumerate(case.lines))  # fmt: skip
            return dataclasses.replace(case, lines=new)

        npu = score_case(run_case(heard(npu_text), config=config, lexicon=lexicon,
                                  semantic=semantic))  # fmt: skip
        cpu = score_case(run_case(heard(cpu_text), config=config, lexicon=lexicon,
                                  semantic=semantic))  # fmt: skip
        npu_outcomes.append(npu)
        cpu_outcomes.append(cpu)
        rows.append({"case": case.case_id, "npu": npu.max_level.label,
                     "cpu": cpu.max_level.label})  # fmt: skip
        print(f"{case.case_id:<6} NPU {npu.max_level.label:<18} CPU {cpu.max_level.label}")
    for key, text in npu_text.items():
        if _norm(text) != _norm(cpu_text[key]):
            differing.append({"npu": text, "cpu": cpu_text[key]})
    print(
        f"\nEncoder output, NPU vs fp32 on this CPU: cosine min {min(cosines):.4f}, "
        f"median {float(np.median(cosines)):.4f}; max abs diff {max(max_abs):.3f}"
    )
    print(f"Lines whose text differs (NPU vs this PC's int8 CPU): {len(differing)}/{len(lines)}")
    for pair in differing:
        print(f"   NPU: {pair['npu']}\n   CPU: {pair['cpu']}")
    print("\nWith the NPU transcripts:")
    print(format_summary(summarise(npu_outcomes)))
    print("\nWith this PC's CPU transcripts:")
    print(format_summary(summarise(cpu_outcomes)))

    slug = re.sub(r"[^a-z0-9]+", "-", args.device.lower()).strip("-")
    out = OUT_DIR / f"aihub-whisper-npu-transcripts-{slug}.json"
    out.write_text(json.dumps({
        "device": args.device, "compile_job": compile_job.url,
        "inference_job": inference_job.url, "lines": len(lines),
        "cosine_min": min(cosines), "cosine_median": float(np.median(cosines)),
        "max_abs_diff": max(max_abs), "cases": rows, "texts_differing": differing,
    }, indent=2), encoding="utf-8")  # fmt: skip
    print(f"Saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
