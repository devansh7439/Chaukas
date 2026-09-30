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
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB, {length:.0f} s of call)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
