"""Record the scripted demo as an MP4: the real Chaukas window, rendered frame by frame.

Plays a case script (default: the digital-arrest demo, DA01) through the app headless,
captures the dashboard every half second of call time, draws any alert card that is showing
on top of it (the critical card fills the screen, as it does for a user), and encodes the
frames with the ffmpeg bundled in imageio-ffmpeg. Nothing is staged: these are the screens
the app shows at those moments.

    uv run --with imageio-ffmpeg python tools/demo_video.py --out chaukas-demo.mp4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FPS = 10
STEP_S = 0.5  # call time between captured frames: each is shown for STEP_S of video
SIZE = (1440, 920)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", type=Path, default=ROOT / "eval" / "cases" / "DA01.yaml")
    parser.add_argument("--out", type=Path, default=Path("chaukas-demo.mp4"))
    parser.add_argument(
        "--seconds", type=float, default=0.0, help="call time to record (0: the case)"
    )
    parser.add_argument("--by", default="", help="author name for the title card")
    parser.add_argument("--narrate", action="store_true", help="add a spoken narration track")
    args = parser.parse_args()

    import imageio_ffmpeg
    from PySide6.QtCore import QCoreApplication, QEventLoop, QRect, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    from chaukas.evaluation.cases import load_case
    from chaukas.ui.app import ALERT_WINDOWS, create_app, load_ui

    case = load_case(args.case)
    length = args.seconds or case.end_time + 6.0
    _app = create_app(headless=True)  # keep the Qt application alive while rendering
    ui = load_ui(case=args.case, headless=True, ablation="E", config_paths=(), speed=1.0,
                 size=SIZE, settings_file=None)  # fmt: skip

    def settle(ms: int = 250) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def card(title: str, lines: list[str]) -> QImage:
        image = QImage(SIZE[0], SIZE[1], QImage.Format.Format_RGB888)
        image.fill(QColor("#13203A"))
        painter = QPainter(image)
        painter.fillRect(0, 0, 18, SIZE[1], QColor("#E07B2E"))
        painter.setPen(QColor("#F6F3EC"))
        painter.setFont(QFont("Segoe UI", 54, QFont.Weight.Bold))
        painter.drawText(QRect(110, 250, 1220, 120), Qt.AlignmentFlag.AlignLeft, title)
        painter.setFont(QFont("Segoe UI", 22))
        painter.setPen(QColor("#C9D2E3"))
        for i, line in enumerate(lines):
            painter.drawText(QRect(110, 400 + i * 52, 1240, 50), Qt.AlignmentFlag.AlignLeft, line)
        painter.end()
        return image

    def frame(t: float) -> QImage:
        base = ui.main_window.grabWindow().convertToFormat(QImage.Format.Format_RGB888)
        base = base.scaled(SIZE[0], SIZE[1])
        painter = QPainter(base)
        for name in ALERT_WINDOWS:
            window = ui.window(name)
            if not window.isVisible():
                continue
            alert = window.grabWindow()
            if name == "criticalWindow":  # full screen for the user, so full frame here
                painter.drawImage(QRect(0, 0, *SIZE), alert)
            else:  # a card at the right edge, as on the desktop
                scaled = alert.scaledToHeight(min(alert.height(), SIZE[1] - 80))
                painter.drawImage(SIZE[0] - scaled.width() - 24, 40, scaled)
        painter.fillRect(0, SIZE[1] - 44, SIZE[0], 44, QColor(19, 32, 58, 220))
        painter.setPen(QColor("#F6F3EC"))
        painter.setFont(QFont("Segoe UI", 13))
        painter.drawText(QRect(20, SIZE[1] - 40, SIZE[0] - 40, 36), Qt.AlignmentFlag.AlignVCenter,
                         f"Chaukas · scripted digital-arrest call (DA01) · the real app window · "
                         f"call time {int(t) // 60:02d}:{int(t) % 60:02d}")  # fmt: skip
        painter.end()
        return base

    writer = imageio_ffmpeg.write_frames(
        str(args.out),
        SIZE,
        fps=FPS,
        codec="libx264",
        pix_fmt_in="rgb24",
        quality=8,
        macro_block_size=8,
    )
    writer.send(None)

    def send(image: QImage, seconds: float) -> None:
        image = image.convertToFormat(QImage.Format.Format_RGB888)
        row = SIZE[0] * 3
        data = bytes(image.constBits())
        stride = image.bytesPerLine()
        pixels = b"".join(data[y * stride : y * stride + row] for y in range(SIZE[1]))
        for _ in range(max(1, round(seconds * FPS))):
            writer.send(pixels)

    send(
        card(
            "Chaukas  ·  चौकस",
            [
                "An on-device guardian against phone-scam manipulation on Windows PCs.",
                "What follows is a scripted digital-arrest call played through the real app.",
                "A fake CBI officer, a threat, “don’t tell anyone”, then a bank transfer page.",
                *([f"By {args.by}"] if args.by else []),
            ],
        ),
        5.0,
    )
    t = 0.0
    while t <= length:
        ui.bridge.jump(t)
        settle()
        send(frame(t), STEP_S)
        t += STEP_S
    send(
        card(
            "Chaukas never blocks you.",
            [
                "It makes you pause, shows you why, and lets you decide.",
                "Speech recognition, detection and the risk engine all run on the PC.",
                "github.com/devansh7439/Chaukas  ·  Apache-2.0",
            ],
        ),
        5.0,
    )
    writer.close()
    ui.close()
    QCoreApplication.processEvents()
    if args.narrate:
        narrate(args.out, total_s=5.0 + (int(length / STEP_S) + 1) * STEP_S + 5.0)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB, {length:.0f} s of call)")
    return 0


# (seconds into the video, words; "Chow-kus" so the voice says the name right).
# The call starts 5 s in, after the title card; the demo's
# alerts fire at 8.5 s (notice), 19.9 s (warning) and 29.0 s (critical) of call time.
NARRATION = (
    (0.5, "Chow-kus is an on-device guardian against scam calls on Windows PCs."),
    (6.0, "A caller claims to be from the CBI. Chow-kus transcribes the call on the laptop."),
    (13.8, "A notice: someone may be pressuring you, with the exact words behind it."),
    (25.0, "Don't tell anyone, stay on camera: that isolation raises a warning."),
    (34.2, "A bank page opens. Chow-kus pauses the whole screen and shows every reason, "
           "with its time."),
    (45.5, "Nothing is blocked. The person decides."),
    (53.8, "Speech runs on the PC, and Whisper's encoder on the Snapdragon NPU."),
)  # fmt: skip


def narrate(video: Path, *, total_s: float) -> None:
    """Speak NARRATION with a Windows voice (Indian English if installed) and mix it into
    ``video``. Needs the winrt speech packages (see audio_eval.py)."""
    import asyncio
    import subprocess
    import tempfile
    import wave

    import imageio_ffmpeg
    import numpy as np
    from tools.audio_eval import _speak

    from chaukas.asr.benchmark import load_wav

    rate = 16_000
    track = np.zeros(int(total_s * rate) + rate, dtype=np.float32)
    free_from = 0.0
    with tempfile.TemporaryDirectory() as folder:
        for i, (start, words) in enumerate(NARRATION):
            wav = Path(folder) / f"line{i}.wav"
            asyncio.run(_speak(words, ("Ravi", "David"), wav))
            speech = load_wav(wav)
            begin = max(start, free_from)  # never talk over the previous line
            first = int(begin * rate)
            end = min(len(track), first + len(speech))
            track[first:end] += speech[: end - first]
            free_from = begin + len(speech) / rate + 0.3
        audio = Path(folder) / "narration.wav"
        with wave.open(str(audio), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes((np.clip(track, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
        silent = Path(folder) / "silent.mp4"
        video.replace(silent)
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(silent),
             "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest",
             str(video)],
            check=True,
        )  # fmt: skip


if __name__ == "__main__":
    sys.exit(main())
