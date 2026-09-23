"""Live mode: lines and screen events arriving from other threads, and the live services."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication

from chaukas.core.models import ContextEvent, ContextKind, HeardLine, Stream
from chaukas.ui.app import create_app, load_ui


@pytest.fixture(scope="module")
def app() -> QGuiApplication:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return create_app(headless=True)


def pump_until(app: QGuiApplication, condition: object, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():  # type: ignore[operator]
            return True
        time.sleep(0.01)
    return False


class TestThreadSafeInput:
    def test_a_line_posted_from_another_thread_reaches_the_screen(
        self, app: QGuiApplication, tmp_path: Path
    ) -> None:
        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True, ablation="E")
        ui.bridge.jump(10.0)
        line = HeardLine(stream=Stream.CALLER, t_start=6.0, t_end=9.0,
                         text="CBI se bol raha hoon, arrest warrant hai")  # fmt: skip
        worker = threading.Thread(target=ui.bridge.post_line, args=(line,))
        worker.start()
        worker.join()
        assert pump_until(app, lambda: ui.bridge.transcript)
        assert ui.bridge.view["level"] == "notice"
        ui.close()

    def test_a_screen_event_posted_from_another_thread_is_context(
        self, app: QGuiApplication, tmp_path: Path
    ) -> None:
        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True, ablation="E")
        ui.bridge.jump(5.0)
        event = ContextEvent(t=5.0, kind=ContextKind.REMOTE_APP_STARTED, detail="AnyDesk.exe")
        threading.Thread(target=ui.bridge.post_context, args=(event,)).start()
        assert pump_until(app, lambda: ui.bridge.transcript)
        assert ui.bridge.transcript[-1]["text"] == "A remote-access app started"
        ui.close()

    def test_status_messages_are_shown(self, app: QGuiApplication, tmp_path: Path) -> None:
        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True)
        threading.Thread(target=ui.bridge.post_status, args=("Listening: Headset",)).start()
        assert pump_until(app, lambda: ui.bridge.liveStatus == "Listening: Headset")
        ui.close()

    def test_session_time_moves_with_the_clock(self, app: QGuiApplication, tmp_path: Path) -> None:
        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True)
        ui.bridge.start()
        first = ui.bridge.session_time()
        time.sleep(0.05)
        assert ui.bridge.session_time() > first
        ui.close()


class TestLiveServices:
    def test_a_missing_speech_model_is_reported_not_fatal(
        self, app: QGuiApplication, tmp_path: Path
    ) -> None:
        pytest.importorskip("faster_whisper")
        from chaukas.ui.services import LiveServices

        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True,
                     config_overrides=[{"asr": {"model": "tiny.en"}}])  # fmt: skip
        services = LiveServices(ui.bridge, ui.config, audio=True, screen=False)
        services.start()
        try:
            assert pump_until(app, lambda: "chaukas setup" in ui.bridge.liveStatus, timeout=20)
        finally:
            services.stop()
            ui.close()

    def test_screen_monitoring_starts_and_stops(self, app: QGuiApplication, tmp_path: Path) -> None:
        pytest.importorskip("psutil")
        from chaukas.ui.services import LiveServices

        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True)
        services = LiveServices(ui.bridge, ui.config, audio=False, screen=True)
        services.start()
        assert services.screen_running
        services.stop()
        assert not services.screen_running
        ui.close()

    def test_real_audio_starts_listening(self, app: QGuiApplication, tmp_path: Path) -> None:
        pytest.importorskip("soundcard")
        pytest.importorskip("tokenizers")
        from chaukas.asr.loader import model_ready
        from chaukas.ui.services import LiveServices

        ui = load_ui(case=None, settings_file=tmp_path / "s.json", headless=True)
        if not model_ready(ui.config.asr):
            ui.close()
            pytest.skip("the configured Whisper model is not downloaded")
        ui.bridge.start()
        services = LiveServices(ui.bridge, ui.config, audio=True, screen=False)
        services.start()
        try:
            ok = pump_until(app, lambda: ui.bridge.liveStatus.startswith(("Listening", "Audio")),
                            timeout=30)  # fmt: skip
            assert ok, ui.bridge.liveStatus
            if ui.bridge.liveStatus.startswith("Audio"):
                pytest.skip(f"no usable audio device: {ui.bridge.liveStatus}")
            assert services.audio_running
        finally:
            services.stop()
            ui.close()
        assert not services.audio_running
