"""Shared fixtures.

``speech`` synthesises real speech with the Windows speech synthesiser (System.Speech), so
audio tests run on genuine speech without recording anyone or committing audio files.
"""

from __future__ import annotations

import subprocess
import sys
import wave
from collections.abc import Callable
from pathlib import Path

import pytest

SpeechFactory = Callable[[str], "object"]


@pytest.fixture(scope="session")
def speech(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], object]:
    """``speech(text)`` -> 16 kHz mono float32 numpy array of that text, spoken."""
    if sys.platform != "win32":
        pytest.skip("speech synthesis uses Windows System.Speech")
    np = pytest.importorskip("numpy")
    folder = tmp_path_factory.mktemp("speech")
    cache: dict[str, object] = {}

    def make(text: str) -> object:
        if text in cache:
            return cache[text]
        path = folder / f"{len(cache)}.wav"
        _synthesise(text, path)
        with wave.open(str(path)) as wav:
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        cache[text] = pcm.astype(np.float32) / 32768.0
        return cache[text]

    return make


def _synthesise(text: str, path: Path) -> None:
    safe = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
        " [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        " [System.Speech.AudioFormat.AudioChannel]::Mono);"
        f"$s.SetOutputToWaveFile('{path}', $f); $s.Speak('{safe}'); $s.Dispose()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0 or not path.exists():
        pytest.skip(f"speech synthesis unavailable: {result.stderr.strip()[:200]}")
