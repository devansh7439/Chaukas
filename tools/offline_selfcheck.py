"""Offline self-check: the live path end to end, with nothing from the network.

Run by ``tools/offline_check.ps1`` while a firewall rule blocks all outbound traffic for
this Python. It checks, in order:

1. the speech model and the voice-detection model load from disk;
2. a synthetic scam call (Windows speech synthesis, written to a temporary WAV) goes
   through the real audio pipeline (voice detection, segmenter, Whisper) into transcript
   lines;
3. those lines, through the signal extractor and the risk engine (configuration E), reach
   a critical alert;
4. one second of the speakers' loopback can be recorded.

Nothing is played aloud. Exit code 0 only if every step passes.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

from chaukas.asr.loader import load_transcriber
from chaukas.audio.pipeline import AudioPipeline
from chaukas.audio.vad import find_vad_model
from chaukas.core.config import load_config
from chaukas.core.models import HeardLine, Level, Segment, Stream
from chaukas.engine.risk import RiskEngine
from chaukas.evaluation.ablation import config_for
from chaukas.evaluation.session import Session
from chaukas.signals.extractor import SignalExtractor
from chaukas.signals.lexicon import Lexicon

CALL = (
    "This is the CBI cyber cell. An arrest warrant has been issued in your name. "
    "Do not tell anyone about this call. Tell me the OTP you just received."
)
RATE = 16_000


def step(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    return ok


def synthesise(text: str, path: Path) -> np.ndarray:
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
        " [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        " [System.Speech.AudioFormat.AudioChannel]::Mono);"
        f"$s.SetOutputToWaveFile('{path}', $f); $s.Speak('{text}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    with wave.open(str(path)) as wav:
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def main() -> int:
    config = load_config()
    results: list[bool] = []

    try:
        transcriber = load_transcriber(config.asr)
        vad_model = find_vad_model()
        results.append(step("models load from disk", vad_model is not None,
                            f"{config.asr.backend} Whisper {config.asr.model}"))  # fmt: skip
    except Exception as exc:  # report, don't crash: the summary must print
        results.append(step("models load from disk", False, str(exc)))
        return 1
    if vad_model is None:
        return 1

    with tempfile.TemporaryDirectory() as folder:
        audio = synthesise(CALL, Path(folder) / "call.wav")
    audio = np.concatenate([audio, np.zeros(RATE * 2, dtype=np.float32)])

    heard: list[HeardLine] = []
    lock = threading.Lock()

    def on_line(line: HeardLine) -> None:
        with lock:
            heard.append(line)

    pipeline = AudioPipeline(config.audio, vad_model=vad_model, transcriber=transcriber,
                             on_line=on_line, redetect_every=config.asr.redetect_every,
                             merge_max_s=config.asr.merge_max_s)  # fmt: skip
    pipeline.add_stream(Stream.CALLER, in_rate=RATE, channels=1)
    pipeline.start()
    started = time.perf_counter()
    try:
        chunk = RATE // 10
        for i in range(0, len(audio), chunk):
            pipeline.feed(Stream.CALLER, audio[i : i + chunk], arrived=(i + chunk) / RATE)
        drained = pipeline.drain(120.0)
    finally:
        pipeline.stop()
    text = " ".join(line.text for line in heard)
    took = time.perf_counter() - started
    results.append(step("audio pipeline transcribes the call", drained and "OTP" in text,
                        f"{len(heard)} lines in {took:.1f} s: {text!r}"))  # fmt: skip

    engine_config = config_for("E")
    session = Session(SignalExtractor(Lexicon.load(), engine_config.signals),
                      RiskEngine.from_config(engine_config), session_id="offline")  # fmt: skip
    for line in sorted(heard, key=lambda item: item.t_start):
        segment = Segment(session_id="offline", seg_id=session.next_segment_id(),
                          stream=line.stream, t_start=line.t_start, t_end=line.t_end,
                          text=line.text)  # fmt: skip
        session.feed_segment(segment)
    final = session.evaluate(session.now + 1.0).state
    results.append(step("the engine raises a critical alert", final.level >= Level.CRITICAL,
                        f"level {final.level.label}"))  # fmt: skip

    try:
        from chaukas.audio.capture import AudioSystem

        system = AudioSystem()
        device = system.default_loopback()
        blocks: list[np.ndarray] = []
        if device is not None:
            capture = system.open(device, lambda samples, at: blocks.append(samples),
                                  clock=time.perf_counter)  # fmt: skip
            capture.start()
            time.sleep(1.0)
            capture.stop()
        results.append(step("the speakers' loopback records", bool(blocks),
                            f"{len(blocks)} blocks from {device}"))  # fmt: skip
    except Exception as exc:
        results.append(step("the speakers' loopback records", False, str(exc)))

    passed = all(results)
    print(f"\n{'ALL PASSED' if passed else 'FAILED'}: {sum(results)}/{len(results)} steps")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
