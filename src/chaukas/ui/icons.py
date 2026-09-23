"""Icon provider: Lucide SVGs rendered in any colour, at any size.

QML asks for ``image://icon/<name>/<rrggbb>``; the SVG's ``currentColor`` is replaced with
that colour and rendered with QtSvg at the requested size, so icons stay crisp at every
DPI and follow the theme's colour tokens. Works with the software renderer too.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

logger = logging.getLogger(__name__)

_DEFAULT_SIZE: Final = 48
_HEX: Final = re.compile(r"^[0-9a-fA-F]{6}$")


class IconProvider(QQuickImageProvider):
    def __init__(self, directory: Path) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._directory = directory
        self._svgs: dict[str, str | None] = {}

    def requestImage(self, id: str, size: QSize, requestedSize: QSize) -> QImage:
        name, _, colour = id.partition("/")
        width = requestedSize.width() if requestedSize.width() > 0 else _DEFAULT_SIZE
        height = requestedSize.height() if requestedSize.height() > 0 else _DEFAULT_SIZE
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        svg = self._svg(name)
        if svg is None:
            return image
        colour = colour if _HEX.match(colour) else "000000"
        renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", f"#{colour}").encode()))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        return image

    def _svg(self, name: str) -> str | None:
        if name not in self._svgs:
            path = self._directory / f"{name}.svg"
            if re.fullmatch(r"[a-z0-9-]+", name) and path.is_file():
                self._svgs[name] = path.read_text(encoding="utf-8")
            else:
                logger.warning("unknown icon %r", name)
                self._svgs[name] = None
        return self._svgs[name]
