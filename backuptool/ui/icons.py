"""Íconos simples dibujados con QPainter en el color del tema.

Así no dependen de archivos externos ni de las fuentes de emoji del sistema, y
cambian de color junto con el tema.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

SIZE = 48   # px lógicos del lienzo; el ícono se escala al tamaño del botón


def _canvas(scale: int = 2) -> tuple[QPixmap, QPainter]:
    pm = QPixmap(SIZE * scale, SIZE * scale)
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pm, p


def _pen(color: QColor, width: float = 3.0) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


# --------------------------------------------------------------------- dibujos
def _images(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(7, 10, 34, 28), 5, 5)
    path = QPainterPath(QPointF(9, 35))
    path.lineTo(19, 23)
    path.lineTo(27, 31)
    path.lineTo(32, 26)
    path.lineTo(39, 34)
    p.drawPath(path)
    p.setBrush(c)
    p.drawEllipse(QPointF(31, 18), 3, 3)


def _audio(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawLine(QPointF(19, 33), QPointF(19, 11))
    p.drawLine(QPointF(19, 11), QPointF(36, 8))
    p.drawLine(QPointF(36, 8), QPointF(36, 30))
    p.setBrush(c)
    p.drawEllipse(QPointF(15, 34), 5, 4)
    p.drawEllipse(QPointF(32, 31), 5, 4)


def _video(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(6, 12, 28, 24), 5, 5)
    path = QPainterPath(QPointF(34, 21))
    path.lineTo(42, 16)
    path.lineTo(42, 32)
    path.lineTo(34, 27)
    p.drawPath(path)
    p.setBrush(c)
    tri = QPainterPath(QPointF(16, 18))
    tri.lineTo(25, 24)
    tri.lineTo(16, 30)
    tri.closeSubpath()
    p.drawPath(tri)


def _documents(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(12, 6))
    path.lineTo(29, 6)
    path.lineTo(37, 14)
    path.lineTo(37, 42)
    path.lineTo(12, 42)
    path.closeSubpath()
    p.drawPath(path)
    p.drawPolyline([QPointF(29, 6), QPointF(29, 14), QPointF(37, 14)])
    for y in (21, 27, 33):
        p.drawLine(QPointF(17, y), QPointF(32, y))


def _mail(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(6, 12, 36, 25), 4, 4)
    p.drawPolyline([QPointF(8, 15), QPointF(24, 27), QPointF(40, 15)])


def _security(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QPointF(16, 24), 8, 8)
    p.drawLine(QPointF(24, 24), QPointF(42, 24))
    p.drawLine(QPointF(36, 24), QPointF(36, 31))
    p.drawLine(QPointF(41, 24), QPointF(41, 30))


def _games(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(5, 15, 38, 20), 10, 10)
    p.drawLine(QPointF(14, 21), QPointF(14, 29))
    p.drawLine(QPointF(10, 25), QPointF(18, 25))
    p.setBrush(c)
    p.drawEllipse(QPointF(31, 22), 2, 2)
    p.drawEllipse(QPointF(36, 27), 2, 2)


def _bookmarks(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(14, 6))
    path.lineTo(34, 6)
    path.lineTo(34, 42)
    path.lineTo(24, 33)
    path.lineTo(14, 42)
    path.closeSubpath()
    p.drawPath(path)


def _drivers(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(13, 13, 22, 22), 3, 3)
    p.drawRect(QRectF(19, 19, 10, 10))
    for k in (18, 24, 30):
        p.drawLine(QPointF(k, 6), QPointF(k, 13))
        p.drawLine(QPointF(k, 35), QPointF(k, 42))
        p.drawLine(QPointF(6, k), QPointF(13, k))
        p.drawLine(QPointF(35, k), QPointF(42, k))


def _wifi(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    for r in (8, 15, 22):
        p.drawArc(QRectF(24 - r, 38 - r, 2 * r, 2 * r), 45 * 16, 90 * 16)
    p.setBrush(c)
    p.drawEllipse(QPointF(24, 37), 2.5, 2.5)


def _programs(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    for x in (8, 26):
        for y in (8, 26):
            p.drawRoundedRect(QRectF(x, y, 14, 14), 3, 3)


def _folder(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(6, 14))
    path.lineTo(18, 14)
    path.lineTo(22, 18)
    path.lineTo(42, 18)
    path.lineTo(42, 38)
    path.lineTo(6, 38)
    path.closeSubpath()
    p.drawPath(path)


def _drive(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(6, 15, 36, 18), 4, 4)
    p.setBrush(c)
    p.drawEllipse(QPointF(35, 24), 2, 2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(11, 24), QPointF(24, 24))


def _usb(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawRoundedRect(QRectF(15, 18, 18, 24), 3, 3)
    p.drawRect(QRectF(19, 7, 10, 11))
    p.drawLine(QPointF(22, 11), QPointF(22, 13))
    p.drawLine(QPointF(26, 11), QPointF(26, 13))


def _check(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 4))
    p.drawEllipse(QPointF(24, 24), 17, 17)
    p.drawPolyline([QPointF(16, 24), QPointF(22, 30), QPointF(32, 18)])


def _clock(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawEllipse(QPointF(24, 24), 17, 17)
    p.drawPolyline([QPointF(24, 13), QPointF(24, 24), QPointF(31, 29)])


def _warning(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(24, 7))
    path.lineTo(42, 39)
    path.lineTo(6, 39)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(24, 18), QPointF(24, 28))
    p.setBrush(c)
    p.drawEllipse(QPointF(24, 33.5), 1.8, 1.8)


_DRAWERS = {
    "images": _images, "audio": _audio, "video": _video, "documents": _documents,
    "mail": _mail, "security": _security, "saved_games": _games,
    "bookmarks": _bookmarks, "drivers": _drivers, "wifi": _wifi, "programs": _programs,
    "folder": _folder, "drive": _drive, "usb": _usb, "check": _check, "warning": _warning,
    "clock": _clock,
}

_cache: dict[tuple[str, str], QIcon] = {}


def icon(name: str, color: str) -> QIcon:
    """Ícono por nombre ("images", "wifi"...) dibujado en el color pedido."""
    key = (name, color)
    if key not in _cache:
        pm, p = _canvas()
        _DRAWERS.get(name, _folder)(p, QColor(color))
        p.end()
        _cache[key] = QIcon(pm)
    return _cache[key]
