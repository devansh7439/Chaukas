"""Record Hinglish test clips in your own voice, then measure how well Chaukas hears them.

Speech recognition has only been measured on synthetic English speech. This tool gives the
first real Hinglish numbers:

    uv run python tools/hinglish_clips.py record     # say 10 short lines (about 2 minutes)
    uv run python tools/hinglish_clips.py bench      # transcribe them and score the signals

What is scored is what matters to Chaukas: does the transcript still produce the right
signals (authority, threat, OTP request, ...)? Whisper may write Hindi in Devanagari or in
Roman letters; the lexicon reads both, so a word error rate would mislead. The transcripts
are printed so you can judge them yourself.

Recordings are saved as WAV files in eval/audio/hinglish/ on this PC only (*.wav is
git-ignored): they are your voice, so they are never committed unless you choose to.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from chaukas.core.config import load_config
from chaukas.core.models import Segment, SignalKind, Stream

RATE = 16_000
SECONDS = 7.0
FOLDER = Path(__file__).resolve().parents[1] / "eval" / "audio" / "hinglish"


@dataclass(frozen=True)
class Clip:
    clip_id: str
    stream: Stream
    text: str  # what to say, naturally, in your own words' rhythm
    expected: frozenset[SignalKind]  # empty: an everyday line that must stay clean


K = SignalKind
CLIPS = (
    Clip("H01", Stream.CALLER, "Main CBI se bol raha hoon, aapke naam pe arrest warrant hai.",
         frozenset({K.AUTHORITY, K.THREAT})),
    Clip("H02", Stream.CALLER, "Yeh baat kisi ko mat batana, ghar walon ko bhi nahi.",
         frozenset({K.ISOLATION})),
    Clip("H03", Stream.CALLER, "Camera on rakho aur call mat kaatna.",
         frozenset({K.SURVEILLANCE})),
    Clip("H04", Stream.CALLER, "Verification ke liye safe account mein paise transfer karo.",
         frozenset({K.MONEY_REQUEST})),
    Clip("H05", Stream.CALLER, "AnyDesk download karo, main aapka computer check karunga.",
         frozenset({K.REMOTE_ACCESS_REQUEST})),
    Clip("H06", Stream.CALLER, "Aapka bank account aaj band ho jayega, jaldi kijiye.",
         frozenset({K.THREAT})),
    Clip("H07", Stream.CALLER, "Aapke phone par jo OTP aaya hai, woh mujhe batao.",
         frozenset({K.CREDENTIAL_REQUEST})),
    Clip("H08", Stream.USER, "Saat aath nau paanch do ek.",  # right after H07's request
         frozenset({K.USER_DIGITS_SPOKEN})),
    Clip("H09", Stream.CALLER, "Kal subah gyarah baje doctor ka appointment hai.", frozenset()),
    Clip("H10", Stream.CALLER, "Beta, kal ghar aa jaana, khaana saath khayenge.", frozenset()),
)  # fmt: skip


def record(folder: Path) -> int:
    import soundcard

    folder.mkdir(parents=True, exist_ok=True)
    microphone = soundcard.default_microphone()
    print(f"Microphone: {microphone.name}\nEach line records for {SECONDS:.0f} s after Enter.\n")
    for clip in CLIPS:
        path = folder / f"{clip.clip_id}.wav"
        who = "as the CALLER" if clip.stream is Stream.CALLER else "as YOU, reading out a code"
        print(f"{clip.clip_id} ({who}):\n    {clip.text}")
        if input("    Enter to record, s to skip: ").strip().lower() == "s":
            continue
        with microphone.recorder(samplerate=RATE, channels=1) as recorder:
            audio = recorder.record(numframes=int(RATE * SECONDS))[:, 0]
        _write(path, audio)
        print(f"    saved {path.name} (peak {float(np.abs(audio).max()):.2f})\n")
    return 0


def bench(folder: Path) -> int:
    from chaukas.asr.loader import load_transcriber
    from chaukas.signals.extractor import SignalExtractor
    from chaukas.signals.lexicon import Lexicon

    config = load_config()
    transcriber = load_transcriber(config.asr)
    extractor = SignalExtractor(Lexicon.load(), config.signals)
    found_total = expected_total = false_signals = clean_lines = 0
    t = 0.0
    for index, clip in enumerate(CLIPS):
        path = folder / f"{clip.clip_id}.wav"
        if not path.is_file():
            print(f"{clip.clip_id}: not recorded, skipped")
            continue
        audio = _read(path)
        transcript = transcriber.transcribe(audio)
        segment = Segment(session_id="bench", seg_id=index, stream=clip.stream, t_start=t,
                          t_end=t + len(audio) / RATE, text=transcript.text)  # fmt: skip
        t += len(audio) / RATE + 1.0
        kinds = {signal.kind for signal in extractor.extract(segment)}
        hits = kinds & clip.expected
        found_total += len(hits)
        expected_total += len(clip.expected)
        if not clip.expected:
            clean_lines += 1
            false_signals += len(kinds)
        verdict = (
            f"{len(hits)}/{len(clip.expected)}"
            if clip.expected
            else ("clean" if not kinds else "FALSE SIGNAL")
        )
        print(f"{clip.clip_id} [{transcript.language}, {transcript.ms / 1000:.1f} s] {verdict}")
        print(f"    said:  {clip.text}\n    heard: {transcript.text}")
        if kinds - clip.expected:
            print(f"    extra: {sorted(k.value for k in kinds - clip.expected)}")
    if expected_total:
        print(f"\nExpected signals found: {found_total}/{expected_total}")
    if clean_lines:
        print(f"Signals on everyday lines: {false_signals} (over {clean_lines} lines)")
    return 0


def _write(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm.tobytes())


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path)) as wav:
        if wav.getframerate() != RATE or wav.getnchannels() != 1:
            sys.exit(f"{path.name}: expected 16 kHz mono")
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["record", "bench"])
    parser.add_argument("--dir", type=Path, default=FOLDER, help="where the clips live")
    args = parser.parse_args()
    started = time.perf_counter()
    code = record(args.dir) if args.command == "record" else bench(args.dir)
    print(f"\n({time.perf_counter() - started:.0f} s)")
    return code


if __name__ == "__main__":
    sys.exit(main())
