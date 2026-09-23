"""Two-stream capture through WASAPI (blueprint 6.1), via SoundCard.

* The **caller** is whatever the PC plays: a *loopback* recording of the default output
  device, which is where call apps (WhatsApp, Zoom, Teams, Meet) send the other person's
  voice.
* The **user** is the default microphone.

Windows converts both to 16 kHz mono float32 in shared mode, so chunks are ready for voice
detection as they arrive. SoundCard is pure Python over WASAPI (through cffi), so the same
code runs on x64 and on Windows on ARM64 (Snapdragon), and a loopback keeps delivering
silence while nothing plays, so the session clock never stalls.

Each capture runs one thread that reads 100 ms blocks and hands them on, stamped with the
session clock. Errors in the handler are logged, never raised into the capture thread.
"""

from __future__ import annotations

import logging
import threading
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from chaukas.audio.convert import TARGET_RATE, Samples

logger = logging.getLogger(__name__)

CHUNK_S: Final = 0.1
_CHUNK_FRAMES: Final = int(TARGET_RATE * CHUNK_S)

ChunkHandler = Callable[[Samples, float], None]


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    name: str
    rate: int
    channels: int
    loopback: bool

    def __str__(self) -> str:
        return f"{self.name} ({'loopback' if self.loopback else 'microphone'})"


class Capture:
    """One input stream on its own thread. ``start``, then ``stop``."""

    def __init__(self, source: Any, on_chunk: ChunkHandler, clock: Callable[[], float],
                 name: str) -> None:  # fmt: skip
        self._source = source
        self._on_chunk = on_chunk
        self._clock = clock
        self._name = name
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"chaukas-capture-{self._name}",
                                        daemon=True)  # fmt: skip
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self) -> None:
        try:
            with warnings.catch_warnings():
                # "data discontinuity" at start-up and after a device hiccup is harmless
                warnings.simplefilter("ignore")
                with self._source.recorder(samplerate=TARGET_RATE, channels=1,
                                           blocksize=_CHUNK_FRAMES) as recorder:  # fmt: skip
                    while not self._stop.is_set():
                        block = recorder.record(numframes=_CHUNK_FRAMES)
                        samples = np.ascontiguousarray(block[:, 0], dtype=np.float32)
                        try:
                            self._on_chunk(samples, self._clock())
                        except Exception:
                            logger.exception("audio chunk handler failed (%s)", self._name)
        except Exception as exc:  # the device went away or could not be opened
            self._error = exc
            logger.exception("audio capture stopped (%s)", self._name)


class AudioSystem:
    """Lists devices and opens captures. ``close`` is kept for symmetry; nothing to free."""

    def __init__(self) -> None:
        import soundcard

        self._sc = soundcard

    def close(self) -> None:
        pass

    def devices(self) -> list[Device]:
        """Every microphone and loopback device."""
        return [self._device(mic) for mic in self._sc.all_microphones(include_loopback=True)]

    def default_loopback(self) -> Device | None:
        """The loopback of the default output device: the caller's voice."""
        try:
            speaker = self._sc.default_speaker()
            return self._device(self._sc.get_microphone(id=speaker.id, include_loopback=True))
        except (RuntimeError, IndexError, OSError):
            return None

    def default_microphone(self) -> Device | None:
        """The default recording device: the user's voice."""
        try:
            return self._device(self._sc.default_microphone())
        except (RuntimeError, IndexError, OSError):
            return None

    def open(
        self, device: Device, on_chunk: ChunkHandler, *, clock: Callable[[], float]
    ) -> Capture:
        """A capture (not yet started) that calls ``on_chunk(samples, session_time)``."""
        source = self._sc.get_microphone(id=device.id, include_loopback=device.loopback)
        kind = "caller" if device.loopback else "user"
        return Capture(source, on_chunk, clock, kind)

    @staticmethod
    def _device(mic: Any) -> Device:
        return Device(id=str(mic.id), name=str(mic.name), rate=TARGET_RATE, channels=1,
                      loopback=bool(getattr(mic, "isloopback", False)))  # fmt: skip
