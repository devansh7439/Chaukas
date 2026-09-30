"""Is a call happening? During a real call the call app holds the microphone; during a film
or a news clip nothing does. Windows records which apps are using the microphone right now."""

from __future__ import annotations

import sys

import pytest

from chaukas.context.calls import CallProbe, apps_in_use, microphone_users, own_executables

OWN = r"C:\Users\me\AppData\Roaming\uv\python\cpython-3.12\python.exe"


class TestRecords:
    def test_an_app_holding_the_microphone_now_has_no_stop_time(self) -> None:
        records = {
            r"C:#Users#me#AppData#Roaming#Zoom#bin#Zoom.exe": (100, 0),  # in use now
            r"C:#Program Files#Google#Chrome#Application#chrome.exe": (100, 200),  # used before
            "5319275A.WhatsAppDesktop_cv1g1gvanyjgm": (300, 0),  # a Store app, in use now
            "Microsoft.Copilot_8wekyb3d8bbwe": (0, 0),  # never used
        }
        assert apps_in_use(records, exclude=()) == [
            r"C:\Users\me\AppData\Roaming\Zoom\bin\Zoom.exe",
            "5319275A.WhatsAppDesktop_cv1g1gvanyjgm",
        ]

    def test_chaukas_own_microphone_capture_is_not_a_call(self) -> None:
        records = {OWN.replace("\\", "#"): (100, 0)}
        assert apps_in_use(records, exclude=[OWN.upper()]) == []


class TestProbe:
    def test_says_call_when_another_app_uses_the_microphone(self) -> None:
        probe = CallProbe(read=lambda: {"C:#Zoom.exe": (1, 0)}, exclude=())
        assert probe() is True

    def test_says_no_call_when_nothing_else_uses_it(self) -> None:
        assert CallProbe(read=lambda: {"C:#Zoom.exe": (1, 2)}, exclude=())() is False

    def test_unknown_when_the_records_cannot_be_read(self) -> None:
        assert CallProbe(read=lambda: None, exclude=())() is None

        def broken() -> dict[str, tuple[int, int]]:
            raise OSError("registry unavailable")

        assert CallProbe(read=broken, exclude=())() is None


def needs_microphone_records() -> None:
    """A PC where apps have used the microphone has privacy records; a fresh machine (a CI
    server) has none, and then the probe rightly answers "unknown"."""
    from chaukas.context.calls import read_records

    if read_records() is None:
        pytest.skip("this machine has no microphone privacy records (e.g. a fresh CI server)")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows privacy records")
def test_this_pc_has_readable_microphone_records() -> None:
    needs_microphone_records()
    assert microphone_users(exclude=()) is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows privacy records")
def test_chaukas_recording_the_microphone_itself_is_not_a_call() -> None:
    # Found live: Windows records the resolved interpreter path, so the exclusion must
    # include it; otherwise Chaukas's own capture looked like a call app.
    import threading
    import time

    needs_microphone_records()
    soundcard = pytest.importorskip("soundcard")
    try:
        microphone = soundcard.default_microphone()
    except Exception:
        pytest.skip("no microphone")
    done = threading.Event()

    def record() -> None:
        import warnings

        with warnings.catch_warnings():  # SoundCard warns on gaps; only the probe is tested
            warnings.simplefilter("ignore")
            with microphone.recorder(samplerate=16000, channels=1) as recorder:
                while not done.is_set():
                    recorder.record(numframes=1600)

    thread = threading.Thread(target=record, daemon=True)
    thread.start()
    time.sleep(2.0)
    try:
        users = microphone_users(exclude=own_executables())
        assert CallProbe()() is False, users
    finally:
        done.set()
        thread.join(5.0)
