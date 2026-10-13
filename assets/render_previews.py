"""
Renders the README previews (animated GIFs, light + dark) with the real engine.
Usage:  python assets/render_previews.py      (needs Pillow: pip install pillow)
"""
import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from thinking_orbs import STATES, paint_orb, resolvePreset  # noqa: E402

THEMES = {"dark": ("#0b0b0c", "#8a8a8e"), "light": ("#f7f7f5", "#6b6b70")}
FPS, SECONDS = 20, 4.0
CELL, BIG, SMALL = 136, 128, 40  # 64 drawn at 2x, 20 drawn at 2x
W, H = CELL * len(STATES), 230


def render(theme: str) -> list[Image.Image]:
    bg, fg = THEMES[theme]
    dark = theme == "dark"
    font = QFont("DejaVu Sans")
    font.setPixelSize(13)
    frames = []
    for n in range(int(FPS * SECONDS)):
        secs = 10 + n / FPS  # shared clock, like the widget
        img = QImage(W, H, QImage.Format.Format_RGB32)
        img.fill(QColor(bg))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for i, state in enumerate(STATES):
            x = i * CELL
            for size, side, y in ((64, BIG, 8), (20, SMALL, 146)):
                t = secs * resolvePreset(state, size)[1]
                paint_orb(p, QRectF(x + (CELL - side) / 2, y, side, side), state, size, t, dark)
            p.setPen(QColor(fg))
            p.setFont(font)
            p.drawText(QRectF(x, 196, CELL, 24), Qt.AlignmentFlag.AlignCenter, state)
        p.end()
        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        frames.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("L").point(lambda v: (v // 8) * 8 + 4 if 4 < v < 251 else v))
    return frames


if __name__ == "__main__":
    app = QApplication([])
    for theme in THEMES:
        frames = render(theme)
        out = os.path.join(HERE, f"orbs-{theme}.gif")
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
        print(out, os.path.getsize(out) // 1024, "KB")
