"""``chaukas benchmark``: reproducible speech-recognition timing, with the hardware used.

Runs Whisper on one clip (warm-up first, then ``runs`` timed calls) and reports where the
time goes (encoder vs decoder), which execution providers ONNX Runtime actually bound,
whether a requested NPU fell back to the CPU, and the real-time factor. The result is a
plain dict, printed and optionally saved as JSON, so a Snapdragon run and a CPU run can be
compared line by line.
"""

from __future__ import annotations

import platform
import statistics
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any, Final

import numpy as np

from chaukas.asr.whisper_onnx import WhisperOnnx
from chaukas.audio.convert import TARGET_RATE, Samples
from chaukas.core.errors import ChaukasError

# About 10 s: one Whisper window, the kind of sentence a scam call is made of.
DEFAULT_SPEECH: Final = (
    "This is the CBI cyber cell. An arrest warrant has been issued in your name. "
    "Do not tell anyone. Please tell me the OTP you just received."
)


def benchmark(whisper: WhisperOnnx, audio: Samples, *, runs: int, model: str) -> dict[str, Any]:
    """Time ``runs`` transcriptions of ``audio`` after one warm-up call."""
    import onnxruntime as ort

    if runs < 1:
        raise ValueError(f"runs must be at least 1, got {runs}")
    whisper.transcribe(audio)  # warm-up: the first call pays one-off graph set-up
    totals: list[float] = []
    encoder: list[float] = []
    decoder: list[float] = []
    text = ""
    for _ in range(runs):
        transcript = whisper.transcribe(audio)
        timing = whisper.last_timing
        assert timing is not None  # set by every transcribe call
        totals.append(transcript.ms)
        encoder.append(timing.encoder_ms)
        decoder.append(timing.decoder_ms)
        text = transcript.text
    runtime = whisper.runtime
    audio_s = len(audio) / TARGET_RATE
    total_ms = statistics.median(totals)
    return {
        "machine": platform.machine(),
        "processor": platform.processor(),
        "os": platform.platform(),
        "on_battery": on_battery(),  # Windows throttles the CPU hard on battery
        "onnxruntime": ort.__version__,
        "model": model,
        "requested_device": runtime.requested,
        "device": runtime.device,
        "fallback": runtime.fallback,
        "note": runtime.note,
        "encoder_providers": list(runtime.encoder_providers),
        "decoder_providers": list(runtime.decoder_providers),
        "encoder_precision": runtime.encoder_precision,
        "decoder_precision": runtime.decoder_precision,
        "audio_s": round(audio_s, 3),
        "runs": runs,
        "total_ms": round(total_ms, 1),
        "encoder_ms": round(statistics.median(encoder), 1),
        "decoder_ms": round(statistics.median(decoder), 1),
        "rtf": round(total_ms / 1000 / audio_s, 4),
        "peak_memory_mb": peak_memory_mb(),
        "text": text,
    }


def peak_memory_mb() -> float | None:
    """This process's peak working set in MB (models, runtime and audio included), or None
    where it cannot be read (not Windows)."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("page_fault_count", wintypes.DWORD),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE  # a 64-bit pseudo-handle
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Counters),
                                           wintypes.DWORD)  # fmt: skip
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters),
                                      counters.cb):  # fmt: skip
        return None
    return round(float(counters.peak_working_set_size) / 1_048_576, 1)


def on_battery() -> bool | None:
    """True on battery, False on mains power, None if unknown (not Windows, or no reading)."""
    if sys.platform != "win32":
        return None
    import ctypes

    class _PowerStatus(ctypes.Structure):
        _fields_ = [
            ("ac_line_status", ctypes.c_ubyte),
            ("battery_flag", ctypes.c_ubyte),
            ("battery_life_percent", ctypes.c_ubyte),
            ("system_status_flag", ctypes.c_ubyte),
            ("battery_life_time", ctypes.c_ulong),
            ("battery_full_life_time", ctypes.c_ulong),
        ]

    status = _PowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    return {0: True, 1: False}.get(status.ac_line_status)  # 255: unknown


def describe(result: dict[str, Any]) -> str:
    """The result as a few human-readable lines."""
    where = result["device"].upper()
    if result["fallback"]:
        where += f" (asked for {result['requested_device'].upper()}: {result['note']})"
    return "\n".join([
        f"Machine:           {result['machine']}  ({result['processor'] or 'unknown CPU'})"
        + ("  ON BATTERY: expect slower, throttled numbers" if result["on_battery"] else ""),
        f"Model:             {result['model']}  on ONNX Runtime {result['onnxruntime']}",
        f"Encoder runs on:   {where}  [{', '.join(result['encoder_providers'])}]",
        f"                   {result['encoder_precision']}",
        f"Decoder runs on:   {', '.join(result['decoder_providers'])}",
        f"                   {result['decoder_precision']}",
        f"Audio:             {result['audio_s']:.1f} s, median of {result['runs']} runs",
        f"Speech-to-text:    {result['total_ms']:.0f} ms"
        f"  (encoder {result['encoder_ms']:.0f} ms, decoder {result['decoder_ms']:.0f} ms)",
        f"Real-time factor:  {result['rtf']:.3f}  (below 1 is faster than real time)",
        f"Peak memory:       {result['peak_memory_mb'] or '-'} MB  (whole process)",
        f"Heard:             {result['text']!r}",
    ])  # fmt: skip


def load_wav(path: Path) -> Samples:
    """A 16 kHz mono 16-bit WAV file as float32 samples."""
    try:
        with wave.open(str(path)) as wav:
            if wav.getframerate() != TARGET_RATE or wav.getnchannels() != 1:
                raise ChaukasError(f"{path}: expected 16 kHz mono, got {wav.getframerate()} Hz, "
                                   f"{wav.getnchannels()} channels")  # fmt: skip
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    except (OSError, wave.Error) as exc:
        raise ChaukasError(f"cannot read {path}: {exc}") from exc
    samples: Samples = pcm.astype(np.float32) / 32768.0
    return samples


def synthesize(text: str = DEFAULT_SPEECH) -> Samples:
    """``text`` spoken by Windows' built-in voice (no network, nothing played aloud)."""
    if sys.platform != "win32":
        raise ChaukasError("built-in speech needs Windows; pass --audio FILE.wav instead")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "speech.wav"
        safe = text.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
            " [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
            " [System.Speech.AudioFormat.AudioChannel]::Mono);"
            f"$s.SetOutputToWaveFile('{path}', $f); $s.Speak('{safe}'); $s.Dispose()"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=True, capture_output=True, timeout=60,
            )  # fmt: skip
        except (OSError, subprocess.SubprocessError) as exc:
            raise ChaukasError(f"speech synthesis failed ({exc}); pass --audio FILE.wav") from exc
        return load_wav(path)
