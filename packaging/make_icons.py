"""Render the application icon (SVG defined in motelmg/ui/icons.py) to the
PNG / ICO / ICNS files used by the installers. Requires PySide6 and Pillow."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from motelmg.ui.icons import APP_ICON_SVG  # noqa: E402

OUT = ROOT / "motelmg" / "resources" / "icons"


def render(size: int) -> QImage:
    renderer = QSvgRenderer(QByteArray(APP_ICON_SVG.encode()))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def main() -> None:
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "app.svg").write_text(APP_ICON_SVG, encoding="utf-8")
    render(512).save(str(OUT / "app.png"))
    render(256).save(str(OUT / "app-256.png"))
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed: skipping .ico/.icns")
        return
    base = Image.open(OUT / "app.png").convert("RGBA")
    base.save(OUT / "app.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    try:
        base.save(OUT / "app.icns")
    except (OSError, ValueError) as exc:  # pragma: no cover - platform specific
        print(f"ICNS not written: {exc}")
    print(f"Icons written to {OUT}")


if __name__ == "__main__":
    main()
