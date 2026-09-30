"""Evaluate cases through the audio chain: speech synthesis -> Whisper -> detection.

`chaukas eval` feeds the scripted text straight to the detector. This tool speaks every
line with a Windows voice (Indian-English voices where installed: the caller as Ravi, the
user as Heera), transcribes the audio with Chaukas's own Whisper, puts what Whisper heard
in place of the script, and scores each case exactly like `chaukas eval`, next to the
text-only result. It measures what speech recognition costs detection. It is still
synthetic speech, not a real call: no accents beyond the voice, no line noise.

Only English cases are used: no Hindi voice is installed, and an English voice reading
romanised Hindi would measure the voice, not Chaukas.

    uv run --with winrt-Windows.Media.SpeechSynthesis --with winrt-Windows.Storage.Streams ^
        --with winrt-Windows.Foundation --with winrt-Windows.Foundation.Collections ^
        python tools/audio_eval.py eval/redteam eval/remote
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
import tempfile
from pathlib import Path

from chaukas.asr.benchmark import load_wav
from chaukas.asr.loader import load_transcriber
from chaukas.core.models import Stream
from chaukas.evaluation.ablation import config_for
from chaukas.evaluation.cases import Case, load_cases
from chaukas.evaluation.metrics import CaseOutcome, score_case, summarise
from chaukas.evaluation.report import format_summary
from chaukas.evaluation.runner import run_case
from chaukas.signals.lexicon import Lexicon
from chaukas.signals.semantic import load_semantic

VOICES = {Stream.CALLER: ("Ravi", "David"), Stream.USER: ("Heera", "Zira")}


async def _speak(text: str, names: tuple[str, ...], path: Path) -> str:
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer
    from winrt.windows.storage.streams import DataReader

    synth = SpeechSynthesizer()
    voices = list(SpeechSynthesizer.all_voices)
    voice = next((v for name in names for v in voices if name in v.display_name), None)
    if voice is not None:
        synth.voice = voice
    stream = await synth.synthesize_text_to_stream_async(text)
    reader = DataReader(stream.get_input_stream_at(0))
    size = await reader.load_async(stream.size)
    data = bytearray(size)
    reader.read_bytes(data)
    path.write_bytes(bytes(data))
    return str(synth.voice.display_name)


def heard(case: Case, whisper: object, folder: Path) -> tuple[Case, list[tuple[str, str]]]:
    """The case with every line replaced by what Whisper heard from its spoken audio."""
    lines = []
    changes = []
    for i, line in enumerate(case.lines):
        wav = folder / f"{case.case_id}-{i}.wav"
        asyncio.run(_speak(line.text, VOICES[line.stream], wav))
        text = whisper.transcribe(load_wav(wav)).text.strip()  # type: ignore[attr-defined]
        lines.append(dataclasses.replace(line, text=text))
        changes.append((line.text, text))
    return dataclasses.replace(case, lines=tuple(lines)), changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", type=Path, nargs="+")
    parser.add_argument("--show", action="store_true", help="print every line as heard")
    args = parser.parse_args()

    config = config_for("E")
    lexicon = Lexicon.load()
    semantic = load_semantic(config.signals.semantic)
    whisper = load_transcriber(config.asr)
    cases = [c for folder in args.folders for c in load_cases(folder) if c.language == "english"]

    text_outcomes: list[CaseOutcome] = []
    audio_outcomes: list[CaseOutcome] = []
    print(f"{'case':<6} {'text':<18} {'audio':<18} changed words")
    with tempfile.TemporaryDirectory() as folder:
        for case in cases:
            spoken, changes = heard(case, whisper, Path(folder))
            text = score_case(run_case(case, config=config, lexicon=lexicon, semantic=semantic))
            audio = score_case(run_case(spoken, config=config, lexicon=lexicon, semantic=semantic))
            text_outcomes.append(text)
            audio_outcomes.append(audio)
            differing = sum(1 for script, got in changes if _norm(script) != _norm(got))
            print(f"{case.case_id:<6} {text.max_level.label:<18} {audio.max_level.label:<18}"
                  f" {differing}/{len(changes)} lines differ")  # fmt: skip
            if args.show:
                for script, got in changes:
                    if _norm(script) != _norm(got):
                        print(f"         script: {script}\n         heard:  {got}")
    print("\nText only (the script):")
    print(format_summary(summarise(text_outcomes)))
    print("\nThrough audio (spoken, then heard by Whisper):")
    print(format_summary(summarise(audio_outcomes)))
    return 0


def _norm(text: str) -> str:
    return " ".join("".join(c for c in text.lower() if c.isalnum() or c.isspace()).split())


if __name__ == "__main__":
    sys.exit(main())
