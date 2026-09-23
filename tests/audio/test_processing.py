"""Audio processing: format conversion, voice activity detection, segmentation, guards."""

from __future__ import annotations

from collections.abc import Callable

import pytest

np = pytest.importorskip("numpy")

from chaukas.audio.convert import StreamResampler, pcm16_to_float  # noqa: E402
from chaukas.audio.guards import EchoGuard, PlaybackGuard  # noqa: E402
from chaukas.audio.segmenter import Segmenter  # noqa: E402
from chaukas.core.models import Stream  # noqa: E402

WINDOW = 512
RATE = 16_000


def tone(freq: float, seconds: float, rate: int, channels: int = 1) -> object:
    t = np.arange(int(seconds * rate)) / rate
    mono = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(mono, channels) if channels > 1 else mono


def dominant_frequency(signal: object, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(signal))
    return float(np.fft.rfftfreq(len(signal), 1 / rate)[int(np.argmax(spectrum))])


class TestConvert:
    def test_pcm16_bytes_become_floats_in_range(self) -> None:
        raw = np.array([0, 16384, -32768, 32767], dtype=np.int16).tobytes()
        samples = pcm16_to_float(raw)
        assert samples.dtype == np.float32
        assert samples.tolist() == pytest.approx([0.0, 0.5, -1.0, 32767 / 32768])

    def test_stereo_48k_becomes_mono_16k_and_keeps_its_pitch(self) -> None:
        resampler = StreamResampler(in_rate=48_000, channels=2)
        stereo = tone(440.0, 1.0, 48_000, channels=2)
        chunks = [resampler.process(stereo[i : i + 9600]) for i in range(0, len(stereo), 9600)]
        chunks.append(resampler.flush())
        out = np.concatenate(chunks)
        assert out.dtype == np.float32
        assert abs(len(out) - RATE) < 64  # one second in, one second out
        assert dominant_frequency(out, RATE) == pytest.approx(440.0, abs=2.0)

    @pytest.mark.parametrize("rate", [44_100, 48_000, 96_000])
    def test_common_device_rates_become_16k_without_clicks_between_chunks(self, rate: int) -> None:
        resampler = StreamResampler(in_rate=rate, channels=1)
        signal = tone(1000.0, 2.0, rate)
        size = int(rate * 0.1)
        chunks = [resampler.process(signal[i : i + size]) for i in range(0, len(signal), size)]
        out = np.concatenate([*chunks, resampler.flush()])
        assert abs(len(out) - 2 * RATE) < 64
        assert dominant_frequency(out, RATE) == pytest.approx(1000.0, abs=2.0)
        reference = tone(1000.0, 2.0, RATE)
        middle = slice(RATE // 2, RATE + RATE // 2)  # away from the filter's start-up
        lag = int(np.argmax(np.correlate(out[middle], reference[middle][:800], "valid")))
        aligned = out[middle][lag : lag + 8000]
        error = np.abs(aligned - reference[middle][: len(aligned)])
        assert error.max() < 0.05  # no clicks at 100 ms chunk boundaries

    def test_frequencies_above_8khz_are_removed(self) -> None:
        resampler = StreamResampler(in_rate=48_000, channels=1)
        out = np.concatenate([resampler.process(tone(12_000.0, 1.0, 48_000)), resampler.flush()])
        assert np.abs(out[2000:-2000]).max() < 0.05  # would alias to 4 kHz if not filtered

    def test_16k_mono_passes_through(self) -> None:
        resampler = StreamResampler(in_rate=RATE, channels=1)
        samples = tone(300.0, 0.1, RATE)
        assert np.array_equal(resampler.process(samples), samples)


def windows(probabilities: list[float], loud: float = 0.3) -> list[tuple[object, float]]:
    """(window, probability) pairs; speech windows are louder than silence."""
    result = []
    for p in probabilities:
        level = loud if p >= 0.5 else 0.001
        result.append((np.full(WINDOW, level, dtype=np.float32), p))
    return result


def run(segmenter: Segmenter, pairs: list[tuple[object, float]]) -> list[object]:
    out = []
    for window, p in pairs:
        segment = segmenter.push(window, p)
        if segment is not None:
            out.append(segment)
    return out


def make_segmenter(**overrides: float) -> Segmenter:
    params: dict[str, float] = {"threshold": 0.5, "silence_s": 0.6, "max_s": 12.0,
                                "min_speech_s": 0.25, "pad_s": 0.192}  # fmt: skip
    params.update(overrides)
    return Segmenter(Stream.CALLER, rate=RATE, window=WINDOW, **params)


class TestSegmenter:
    W = WINDOW / RATE  # 32 ms

    def test_speech_then_silence_closes_one_segment_with_padding(self) -> None:
        # 10 windows silence, 40 speech (1.28 s), then 25 silence (> 0.6 s)
        segments = run(make_segmenter(), windows([0.0] * 10 + [0.9] * 40 + [0.0] * 25))
        (segment,) = segments
        assert segment.stream is Stream.CALLER
        assert segment.t_start == pytest.approx((10 - 6) * self.W)  # 6 windows of pre-roll
        assert segment.t_end == pytest.approx((50 + 6) * self.W)  # 6 windows of tail
        assert len(segment.samples) == (40 + 12) * WINDOW

    def test_a_short_pause_does_not_split_a_sentence(self) -> None:
        pattern = [0.9] * 20 + [0.1] * 10 + [0.9] * 20 + [0.0] * 25  # 0.32 s pause
        assert len(run(make_segmenter(), windows(pattern))) == 1

    def test_a_click_is_not_speech(self) -> None:
        assert run(make_segmenter(), windows([0.0] * 5 + [0.9] * 3 + [0.0] * 30)) == []

    def test_long_speech_is_cut_at_the_quietest_moment_of_the_last_second(self) -> None:
        segmenter = make_segmenter(max_s=2.0)  # 62.5 windows
        pairs = windows([0.9] * 70)
        quiet_index = 55  # inside the last second before the cap
        pairs[quiet_index] = (np.full(WINDOW, 0.01, dtype=np.float32), 0.6)
        segments = run(segmenter, pairs)
        assert len(segments) == 1
        assert segments[0].t_end == pytest.approx((quiet_index + 1) * self.W)
        rest = segmenter.flush()
        assert rest is not None
        assert rest.t_start == pytest.approx((quiet_index + 1) * self.W)

    def test_flush_emits_speech_in_progress(self) -> None:
        segmenter = make_segmenter()
        assert run(segmenter, windows([0.9] * 20)) == []
        segment = segmenter.flush()
        assert segment is not None
        assert segmenter.flush() is None

    def test_times_start_at_the_given_origin(self) -> None:
        segmenter = Segmenter(Stream.USER, rate=RATE, window=WINDOW, threshold=0.5,
                              silence_s=0.6, max_s=12, min_speech_s=0.25, pad_s=0.0,
                              origin=100.0)  # fmt: skip
        (segment,) = run(segmenter, windows([0.9] * 20 + [0.0] * 25))
        assert segment.t_start == pytest.approx(100.0)

    def test_skip_moves_the_clock_and_closes_speech(self) -> None:
        segmenter = make_segmenter(pad_s=0.0)
        run(segmenter, windows([0.9] * 20))
        closed = segmenter.skip(5.0)  # a gap in the audio (nothing was playing)
        assert closed is not None
        (after,) = run(segmenter, windows([0.9] * 20 + [0.0] * 25))
        assert after.t_start == pytest.approx(20 * self.W + 5.0)


@pytest.fixture(scope="module")
def vad_factory() -> Callable[[], object]:
    pytest.importorskip("onnxruntime")
    from chaukas.audio.vad import SileroVad, find_vad_model

    path = find_vad_model()
    if path is None:
        pytest.skip("no Silero VAD model available")
    return lambda: SileroVad(path)


class TestVad:
    def test_silence_is_not_speech(self, vad_factory: Callable[[], object]) -> None:
        vad = vad_factory()
        pairs = vad.process(np.zeros(RATE, dtype=np.float32))  # type: ignore[attr-defined]
        assert len(pairs) == RATE // WINDOW
        assert max(p for _, p in pairs) < 0.2

    def test_speech_is_speech(
        self, vad_factory: Callable[[], object], speech: Callable[[str], object]
    ) -> None:
        vad = vad_factory()
        pairs = vad.process(speech("Please tell me the OTP you just received."))  # type: ignore[attr-defined]
        probabilities = [p for _, p in pairs]
        assert max(probabilities) > 0.9
        assert sum(p > 0.5 for p in probabilities) > len(probabilities) / 3

    def test_leftover_samples_wait_for_the_next_chunk(
        self, vad_factory: Callable[[], object]
    ) -> None:
        vad = vad_factory()
        assert vad.process(np.zeros(300, dtype=np.float32)) == []  # type: ignore[attr-defined]
        assert len(vad.process(np.zeros(300, dtype=np.float32))) == 1  # type: ignore[attr-defined]


class TestGuards:
    def test_playback_guard_mutes_during_an_alert_and_its_tail(self) -> None:
        guard = PlaybackGuard(tail_s=0.3)
        guard.playing(10.0, 12.0)
        assert not guard.muted(9.9)
        assert guard.muted(11.0)
        assert guard.muted(12.29)
        assert not guard.muted(12.31)

    def test_echo_guard_drops_the_callers_words_heard_by_the_microphone(self) -> None:
        guard = EchoGuard(similarity=0.6)
        guard.caller_said(10.0, 13.0, "Aapke naam pe arrest warrant hai")
        assert guard.is_echo(10.5, 13.2, "naam pe arrest warrant hai")
        assert not guard.is_echo(10.5, 13.2, "Main ne kuch nahi kiya")  # the user's own words
        assert not guard.is_echo(20.0, 22.0, "arrest warrant hai")  # not at the same time
