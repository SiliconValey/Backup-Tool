"""Genera backuptool/resources/icon.png e icon.ico (se ejecuta una sola vez).

    python tools/make_icon.py      (requiere Pillow sólo para el .ico)
"""
import os
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen)

OUT = os.path.join(os.path.dirname(__file__), "..", "backuptool", "resources")


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256.0
    p.scale(s, s)

    # Fondo: cuadrado redondeado con degradé azul → turquesa
    bg = QLinearGradient(0, 0, 256, 256)
    bg.setColorAt(0, QColor("#2f6fdb"))
    bg.setColorAt(1, QColor("#14a39a"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(bg))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)

    # Disco externo
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(44, 150, 168, 62), 18, 18)
    p.setBrush(QColor("#14a39a"))
    p.drawEllipse(QPointF(184, 181), 9, 9)
    p.setBrush(QColor(20, 60, 90, 70))
    p.drawRoundedRect(QRectF(66, 176, 84, 10), 5, 5)

    # Flecha hacia el disco
    arrow = QPainterPath()
    arrow.moveTo(128, 136)
    arrow.lineTo(80, 88)
    arrow.lineTo(108, 88)
    arrow.lineTo(108, 40)
    arrow.lineTo(148, 40)
    arrow.lineTo(148, 88)
    arrow.lineTo(176, 88)
    arrow.closeSubpath()
    p.setBrush(QColor("#ffffff"))
    pen = QPen(QColor("#ffffff"), 10)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPath(arrow)
    p.end()
    return img


def main() -> None:
    QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    big = draw(256)
    big.save(os.path.join(OUT, "icon.png"))
    for n in (16, 24, 32, 48, 64, 128):
        draw(n).save(os.path.join(OUT, f"_icon_{n}.png"))
    try:
        from PIL import Image
        imgs = [Image.open(os.path.join(OUT, f"_icon_{n}.png")) for n in (16, 24, 32, 48, 64, 128)]
        Image.open(os.path.join(OUT, "icon.png")).save(
            os.path.join(OUT, "icon.ico"),
            sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)],
            append_images=imgs)
    finally:
        for n in (16, 24, 32, 48, 64, 128):
            os.remove(os.path.join(OUT, f"_icon_{n}.png"))
    print("Ícono generado en", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
