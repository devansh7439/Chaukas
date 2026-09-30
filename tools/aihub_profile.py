"""Profile Whisper's encoder on a real Snapdragon device through Qualcomm AI Hub.

The encoder is Whisper's fixed cost: every call runs it once over a 30 s window, so it is
most of each sentence's transcription time. This script compiles the same model Chaukas
uses (onnx-community/whisper-small, fp32 encoder; pinned revision) for a Snapdragon device
in AI Hub's cloud, profiles it there, and times the same file on this PC's CPU for
comparison. The profile is saved as JSON next to a short summary.

One-time setup (your token stays on your PC; never paste it anywhere else):

    uv run --with qai-hub qai-hub configure --api_token YOUR_TOKEN

Then:

    uv run --with qai-hub python tools/aihub_profile.py --list-devices
    uv run --with qai-hub python tools/aihub_profile.py --device "Snapdragon X Elite CRD"

Only the encoder model file is uploaded (public weights); no audio or transcript is sent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = "onnx-community/whisper-small"
REVISION = "36050c46d777d46dc4b5f43f6d90574fc38f8732"
ENCODER = "onnx/encoder_model.onnx"
INPUT_SPECS = {"input_features": ((1, 80, 3000), "float32")}
# The paraphrase layer's model, the ARM64 build Chaukas loads on Snapdragon PCs. Chaukas
# runs it on the CPU, so it is profiled on the device's CPU; one sentence of 32 tokens.
PARAPHRASE_REPO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
PARAPHRASE_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
PARAPHRASE_FILE = "onnx/model_qint8_arm64.onnx"
PARAPHRASE_TOKENS = 32
PARAPHRASE_SPECS = dict.fromkeys(
    ("input_ids", "attention_mask", "token_type_ids"), ((1, PARAPHRASE_TOKENS), "int64")
)
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "benchmarks"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", default="Snapdragon X Elite CRD", help="AI Hub device name")
    parser.add_argument(
        "--runtime",
        choices=["onnx", "qnn_dlc"],
        default="onnx",
        help="onnx = ONNX Runtime with the QNN provider, as Chaukas uses",
    )
    parser.add_argument("--list-devices", action="store_true", help="list Snapdragon devices")
    parser.add_argument("--model", type=Path, help="use this encoder file instead of downloading")
    parser.add_argument("--local-only", action="store_true", help="only time the CPU here")
    parser.add_argument("--component", choices=["encoder", "paraphrase"], default="encoder",
                        help="encoder: Whisper's encoder on the NPU; paraphrase: the "
                             "semantic model on the device's CPU, as Chaukas runs it")  # fmt: skip
    args = parser.parse_args()

    if args.list_devices:
        hub = _hub()
        for device in hub.get_devices():
            if "snapdragon" in device.name.lower():
                print(f"{device.name}   ({device.os})")
        return 0

    if args.component == "paraphrase":
        return _paraphrase(args)
    model = args.model or _download_encoder()
    print(f"Encoder: {model} ({model.stat().st_size / 1e6:.0f} MB)")
    cpu_ms = _time_on_this_cpu(model)
    print(f"This PC's CPU (ONNX Runtime): median {cpu_ms:.0f} ms per 30 s window")
    if args.local_only:
        return 0

    hub = _hub()
    device = hub.Device(args.device)
    print(f"Compiling for {args.device} ({args.runtime})... this takes several minutes")
    compile_job = hub.submit_compile_job(
        model=str(model), device=device, name="chaukas-whisper-small-encoder",
        input_specs=INPUT_SPECS, options=f"--target_runtime {args.runtime}",
    )  # fmt: skip
    print(f"  {compile_job.url}")
    target = compile_job.get_target_model()
    if target is None:
        print("Compilation failed; see the job page above.", file=sys.stderr)
        return 1
    print("Profiling on the device...")
    profile_job = hub.submit_profile_job(model=target, device=device,
                                         name="chaukas-whisper-small-encoder")  # fmt: skip
    print(f"  {profile_job.url}")
    profile: dict[str, Any] = profile_job.download_profile()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", args.device.lower()).strip("-")
    out = OUT_DIR / f"aihub-whisper-small-encoder-{slug}-{args.runtime}.json"
    out.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    _summarise(profile, args.device, cpu_ms, compile_job.url, profile_job.url)
    print(f"Full profile saved to {out}")
    return 0


def _paraphrase(args: argparse.Namespace) -> int:
    """The semantic layer's model on the device's CPU, as Chaukas runs it there."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import hf_hub_download

    model = args.model or Path(hf_hub_download(PARAPHRASE_REPO, PARAPHRASE_FILE,
                                               revision=PARAPHRASE_REVISION))  # fmt: skip
    print(f"Paraphrase model: {model} ({model.stat().st_size / 1e6:.0f} MB)")
    hub = _hub()
    device = hub.Device(args.device)
    options = f"--target_runtime {args.runtime} --compute_unit cpu"
    print(f"Compiling for {args.device} ({options})...")
    compile_job = hub.submit_compile_job(
        model=str(model), device=device, name="chaukas-paraphrase-minilm",
        input_specs=PARAPHRASE_SPECS, options=options,
    )  # fmt: skip
    target = compile_job.get_target_model()
    if target is None:
        print(f"Compilation failed; see {compile_job.url}", file=sys.stderr)
        return 1
    profile_job = hub.submit_profile_job(model=target, device=device, options="--compute_unit cpu",
                                         name="chaukas-paraphrase-minilm")  # fmt: skip
    profile: dict[str, Any] = profile_job.download_profile()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", args.device.lower()).strip("-")
    out = OUT_DIR / f"aihub-paraphrase-minilm-{slug}-cpu.json"
    out.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    times = profile.get("execution_summary", {}).get("all_inference_times") or []
    if times:
        print(f"\n{args.device} CPU: median {statistics.median(times) / 1000:.1f} ms per "
              f"{PARAPHRASE_TOKENS}-token sentence ({len(times)} runs)")  # fmt: skip
    print(f"  {compile_job.url}\n  {profile_job.url}\nFull profile saved to {out}")
    return 0


def _hub() -> Any:
    try:
        import qai_hub
    except ImportError:
        sys.exit("qai-hub is not installed here. Run with: uv run --with qai-hub python "
                 "tools/aihub_profile.py ...")  # fmt: skip
    return qai_hub


def _download_encoder() -> Path:
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import hf_hub_download

    print(f"Downloading the fp32 encoder from {REPO} (~350 MB, once)...")
    return Path(hf_hub_download(REPO, ENCODER, revision=REVISION))


def _time_on_this_cpu(model: Path, runs: int = 5) -> float:
    import onnxruntime as ort

    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    features = np.random.default_rng(0).standard_normal((1, 80, 3000)).astype(np.float32)
    session.run(None, {name: features})  # warm-up
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        session.run(None, {name: features})
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def _summarise(profile: dict[str, Any], device: str, cpu_ms: float, *urls: str) -> None:
    summary = profile.get("execution_summary", {})
    micros = summary.get("estimated_inference_time")
    memory = summary.get("estimated_inference_peak_memory")
    units: dict[str, int] = {}
    for layer in profile.get("execution_detail", []):
        unit = str(layer.get("compute_unit", "?"))
        units[unit] = units.get(unit, 0) + 1
    print(
        f"\n{device}: "
        + (
            f"{micros / 1000:.1f} ms per 30 s window"
            if micros
            else f"no inference time in the profile (keys: {sorted(summary)})"
        )
    )
    if memory:
        print(f"  peak memory {memory / 1e6:.0f} MB")
    if units:
        print(
            "  layers by compute unit: " + ", ".join(f"{u} {n}" for u, n in sorted(units.items()))
        )
    if micros:
        print(f"  vs this PC's CPU: {cpu_ms:.0f} ms ({cpu_ms / (micros / 1000):.1f}x)")
    for url in urls:
        print(f"  {url}")


if __name__ == "__main__":
    sys.exit(main())
