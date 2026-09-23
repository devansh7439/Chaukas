"""Two-stream capture through WASAPI (blueprint 6.1), via PyAudioWPatch.

* The **caller** is whatever the PC plays: a *loopback* recording of the default output
  device, which is where call apps (WhatsApp, Zoom, Teams, Meet) send the other person's
  voice.
* The **user** is the default microphone.

Each stream is opened in its device's own format (usually 48 kHz stereo, 16-bit) and
delivered as interleaved float32 chunks of about 100 ms, stamped with the session clock.
The callback runs on PortAudio's thread and does nothing else: it converts and hands the
chunk on. Errors in the handler are logged, never raised into PortAudio.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from chaukas.audio.convert import Samples, pcm16_to_float

logger = logging.getLogger(__name__)

CHUNK_S: Final = 0.1
MAX_CHANNELS: Final = 2

ChunkHandler = Callable[[Samples, float], None]


@dataclass(frozen=True, slots=True)
class Device:
    index: int
    name: str
    rate: int
    channels: int
    loopback: bool

    def __str__(self) -> str:
        kind = "loopback" if self.loopback else "microphone"
        return f"{self.name} ({kind}, {self.rate} Hz, {self.channels} ch)"


class Capture:
    """One open input stream. ``start``, then ``stop`` (which also closes it)."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def start(self) -> None:
        self._stream.start_stream()

    def stop(self) -> None:
        try:
            if self._stream.is_active():
                self._stream.stop_stream()
        finally:
            self._stream.close()


class AudioSystem:
    """Owns the PortAudio session: lists devices and opens captures. Close it when done."""

    def __init__(self) -> None:
        import pyaudiowpatch as pyaudio

        self._pyaudio = pyaudio
        self._pa = pyaudio.PyAudio()

    def close(self) -> None:
        self._pa.terminate()

    def devices(self) -> list[Device]:
        """Every WASAPI microphone and loopback device."""
        wasapi = self._pa.get_host_api_info_by_type(self._pyaudio.paWASAPI)["index"]
        found = []
        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            if info["hostApi"] == wasapi and info["maxInputChannels"] > 0:
                found.append(self._device(info))
        return found

    def default_loopback(self) -> Device | None:
        """The loopback of the default output device: the caller's voice."""
        try:
            return self._device(self._pa.get_default_wasapi_loopback())
        except (OSError, LookupError):
            return None

    def default_microphone(self) -> Device | None:
        """The default recording device: the user's voice."""
        try:
            wasapi = self._pa.get_host_api_info_by_type(self._pyaudio.paWASAPI)
            index = wasapi["defaultInputDevice"]
            if index < 0:
                return None
            return self._device(self._pa.get_device_info_by_index(index))
        except (OSError, LookupError):
            return None

    def open(
        self, device: Device, on_chunk: ChunkHandler, *, clock: Callable[[], float]
    ) -> Capture:
        """Open (not start) a capture that calls ``on_chunk(samples, session_time)``."""
        pyaudio = self._pyaudio

        def callback(
            in_data: bytes | None, frames: int, time_info: Any, status: int
        ) -> tuple[None, int]:
            if in_data:
                try:
                    on_chunk(pcm16_to_float(in_data), clock())
                except Exception:
                    logger.exception("audio chunk handler failed (%s)", device.name)
            return None, pyaudio.paContinue

        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=device.channels,
            rate=device.rate,
            input=True,
            input_device_index=device.index,
            frames_per_buffer=int(device.rate * CHUNK_S),
            stream_callback=callback,
            start=False,
        )
        return Capture(stream)

    @staticmethod
    def _device(info: dict[str, Any]) -> Device:
        return Device(
            index=int(info["index"]),
            name=str(info["name"]),
            rate=int(info["defaultSampleRate"]),
            channels=max(1, min(MAX_CHANNELS, int(info["maxInputChannels"]))),
            loopback=bool(info.get("isLoopbackDevice", False)),
        )
