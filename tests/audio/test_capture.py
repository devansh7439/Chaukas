"""Real audio devices through WASAPI. Skipped where there is no device to open."""

from __future__ import annotations

import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="WASAPI capture is Windows-only")

np = pytest.importorskip("numpy")
pytest.importorskip("pyaudiowpatch")

from chaukas.audio.capture import AudioSystem, Device  # noqa: E402


@pytest.fixture
def system() -> object:
    audio = AudioSystem()
    yield audio
    audio.close()


def test_default_devices_are_found(system: AudioSystem) -> None:
    loopback = system.default_loopback()
    microphone = system.default_microphone()
    if loopback is None or microphone is None:
        pytest.skip("this PC has no default output or microphone")
    assert loopback.loopback
    assert not microphone.loopback
    for device in (loopback, microphone):
        assert device.rate > 0
        assert 1 <= device.channels <= 2
    names = [d.name for d in system.devices()]
    assert loopback.name in names
    assert microphone.name in names


def test_the_microphone_delivers_float_chunks(system: AudioSystem) -> None:
    microphone = system.default_microphone()
    if microphone is None:
        pytest.skip("no microphone")
    chunks: list[object] = []
    arrived = threading.Event()

    def on_chunk(samples: object, at: float) -> None:
        chunks.append(samples)
        arrived.set()

    try:
        capture = system.open(microphone, on_chunk, clock=lambda: 1.0)
    except OSError as exc:
        pytest.skip(f"microphone could not be opened: {exc}")
    capture.start()
    try:
        assert arrived.wait(3.0), "no audio arrived from the microphone"
    finally:
        capture.stop()
    first = chunks[0]
    assert first.dtype == np.float32  # type: ignore[attr-defined]
    assert len(first) % microphone.channels == 0  # type: ignore[arg-type]


def test_a_callback_error_does_not_stop_capture(system: AudioSystem) -> None:
    microphone = system.default_microphone()
    if microphone is None:
        pytest.skip("no microphone")
    calls = {"n": 0}
    second = threading.Event()

    def on_chunk(samples: object, at: float) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        second.set()

    try:
        capture = system.open(microphone, on_chunk, clock=lambda: 1.0)
    except OSError as exc:
        pytest.skip(f"microphone could not be opened: {exc}")
    capture.start()
    try:
        assert second.wait(3.0)
    finally:
        capture.stop()


def test_devices_describe_themselves() -> None:
    device = Device(index=3, name="Headset", rate=48_000, channels=2, loopback=True)
    assert str(device) == "Headset (loopback, 48000 Hz, 2 ch)"
