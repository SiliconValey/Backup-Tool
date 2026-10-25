"""Widgets propios del asistente: barra de pasos, tarjetas de opción, tarjetas de
resultado y barra de espacio en disco. Se dibujan con los colores del tema activo
(themes.current()), así funcionan con todos los temas sin hojas de estilo extra."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from . import themes
from .icons import icon


def _accent_brush(t: themes.Theme, rect: QRectF):
    """Degradé del tema (si tiene) o el color de acento liso."""
    if t.grad:
        g = QLinearGradient(rect.topLeft(), rect.topRight())
        g.setColorAt(0, QColor(t.grad[0]))
        g.setColorAt(1, QColor(t.grad[1]))
        return g
    return QColor(t.accent)


# ============================================================== barra de pasos
class StepHeader(QWidget):
    """● Origen ── ● Qué copiar ── ○ Revisar ... Los pasos ya hechos se pueden clickear."""

    stepClicked = Signal(int)

    def __init__(self, steps: list[str], parent=None):
        super().__init__(parent)
        self.steps = steps
        self.current = 0
        self.max_reachable = 0     # hasta qué paso se puede volver haciendo clic
        self.locked = False        # durante la búsqueda o la copia no se navega
        self.setMinimumHeight(66)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    def set_current(self, index: int) -> None:
        self.current = index
        self.max_reachable = max(self.max_reachable, index)
        self.update()

    def _centers(self) -> list[QPointF]:
        n = len(self.steps)
        margin = 60
        span = max(self.width() - 2 * margin, 1)
        return [QPointF(margin + span * i / max(n - 1, 1), 22) for i in range(n)]

    def _clickable(self, i: int) -> bool:
        return not self.locked and i != self.current and i <= self.max_reachable

    def mouseMoveEvent(self, event) -> None:
        hit = self._hit(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if hit is not None and self._clickable(hit)
                       else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        hit = self._hit(event.position())
        if hit is not None and self._clickable(hit):
            self.stepClicked.emit(hit)

    def _hit(self, pos: QPointF) -> int | None:
        for i, c in enumerate(self._centers()):
            if abs(pos.x() - c.x()) < 50 and pos.y() < 64:
                return i
        return None

    def paintEvent(self, _event) -> None:
        t = themes.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centers = self._centers()
        r = 13
        # Líneas entre pasos
        for i in range(len(centers) - 1):
            a, b = centers[i], centers[i + 1]
            done = i < self.current
            p.setPen(QPen(QColor(t.accent if done else t.border), 3))
            p.drawLine(QPointF(a.x() + r + 4, a.y()), QPointF(b.x() - r - 4, b.y()))
        font = QFont(self.font())
        bold = QFont(font)
        bold.setBold(True)
        for i, (c, name) in enumerate(zip(centers, self.steps)):
            rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            if i <= self.current:
                if i == self.current:   # anillo de brillo en el paso actual
                    p.setPen(QPen(QColor(t.glow or t.accent), 3))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(rect.adjusted(-4, -4, 4, 4))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_accent_brush(t, rect))
                p.drawEllipse(rect)
                p.setPen(QColor(t.accent_text))
            else:
                p.setPen(QPen(QColor(t.border), 2))
                p.setBrush(QColor(t.base))
                p.drawEllipse(rect)
                p.setPen(QColor(t.muted))
            p.setFont(bold)
            mark = "✓" if i < self.current else str(i + 1)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, mark)
            p.setFont(bold if i == self.current else font)
            p.setPen(QColor(t.text if i <= self.current else t.muted))
            p.drawText(QRectF(c.x() - 60, c.y() + r + 6, 120, 20),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)
        p.end()


# ============================================================ tarjeta de opción
class OptionCard(QAbstractButton):
    """Tarjeta tildable con ícono, título y descripción (reemplaza a los QCheckBox)."""

    def __init__(self, icon_name: str, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.title = title
        self.subtitle = subtitle
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(subtitle)
        self.setMinimumSize(200, 74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # Para que el código que usaba QCheckBox siga funcionando
    def text(self) -> str:  # type: ignore[override]
        return self.title

    def sizeHint(self) -> QSize:
        return QSize(230, 74)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        t = themes.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = max(t.radius, 8)
        on = self.isChecked()
        enabled = self.isEnabled()
        hover = self.underMouse() and enabled
        bg = QColor(t.alt_base if on else t.base)
        if on:
            tint = QColor(t.accent)
            tint.setAlpha(28 if t.dark else 22)
            p.setBrush(bg)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rect, radius, radius)
            bg = tint
        border = QColor(t.glow or t.accent) if (on or hover) else QColor(t.border)
        if not enabled:
            border = QColor(t.border)
        p.setBrush(bg)
        p.setPen(QPen(border, 2 if on else 1))
        p.drawRoundedRect(rect, radius, radius)
        if self.hasFocus():
            p.setPen(QPen(QColor(t.glow or t.accent), 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(3, 3, -3, -3), radius - 2, radius - 2)

        # Ícono dentro de un círculo
        circle = QRectF(rect.left() + 12, rect.center().y() - 20, 40, 40)
        p.setPen(Qt.PenStyle.NoPen)
        if on and enabled:
            p.setBrush(_accent_brush(t, circle))
            icon_color = t.accent_text
        else:
            p.setBrush(QColor(t.button))
            icon_color = t.muted
        p.drawEllipse(circle)
        icon(self.icon_name, icon_color).paint(p, circle.adjusted(8, 8, -8, -8).toRect())

        # Textos
        x = circle.right() + 12
        text_w = rect.right() - x - 30
        title_font = QFont(self.font())
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(t.text if enabled else t.muted))
        fm = QFontMetrics(title_font)
        if self.subtitle:
            p.drawText(QRectF(x, rect.top() + 12, text_w, fm.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(self.title, Qt.TextElideMode.ElideRight, int(text_w)))
            small = QFont(self.font())
            small.setPointSizeF(max(self.font().pointSizeF() - 1, 7))
            p.setFont(small)
            p.setPen(QColor(t.muted))
            p.drawText(QRectF(x, rect.top() + 14 + fm.height(), text_w, rect.height() - fm.height() - 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                       self.subtitle)
        else:
            p.drawText(QRectF(x, rect.top(), text_w, rect.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)

        # Tilde en la esquina
        box = QRectF(rect.right() - 24, rect.top() + 9, 15, 15)
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.accent))
            p.drawEllipse(box)
            pen = QPen(QColor(t.accent_text), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawPolyline([QPointF(box.left() + 4, box.center().y()),
                            QPointF(box.left() + 6.5, box.bottom() - 4.5),
                            QPointF(box.right() - 3.5, box.top() + 4.5)])
        else:
            p.setPen(QPen(QColor(t.muted), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(box)
        p.end()


# ============================================================= tarjeta de dato
class StatTile(QWidget):
    """Un número grande con su descripción (pantalla final)."""

    def __init__(self, icon_name: str, caption: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.caption = caption
        self.value = "—"
        self.alert = False
        self.setMinimumSize(170, 96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: str, alert: bool = False) -> None:
        self.value = value
        self.alert = alert
        self.update()

    def paintEvent(self, _event) -> None:
        t = themes.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = max(t.radius, 8)
        p.setPen(QPen(QColor(t.border), 1))
        p.setBrush(QColor(t.alt_base if t.dark else t.base))
        p.drawRoundedRect(rect, radius, radius)
        # franja de color arriba
        band = QRectF(rect.left(), rect.top(), rect.width(), 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.danger) if self.alert else _accent_brush(t, band))
        p.drawRoundedRect(band, 2, 2)
        color = t.danger if self.alert else (t.glow or t.accent)
        icon(self.icon_name, color).paint(p, QRectF(rect.left() + 14, rect.top() + 18, 26, 26).toRect())
        big = QFont(self.font())
        big.setPointSizeF(self.font().pointSizeF() + 9)
        big.setBold(True)
        p.setFont(big)
        p.setPen(QColor(t.danger if self.alert else t.text))
        p.drawText(QRectF(rect.left() + 50, rect.top() + 10, rect.width() - 60, 40),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.value)
        p.setFont(self.font())
        p.setPen(QColor(t.muted))
        p.drawText(QRectF(rect.left() + 14, rect.top() + 54, rect.width() - 24, 34),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                   self.caption)
        p.end()


# ========================================================= barra de espacio
class SpaceBar(QWidget):
    """Ocupado | lo que se va a copiar | libre, sobre el total de la unidad destino."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total = 0
        self.free = 0
        self.needed = 0
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, total: int, free: int, needed: int) -> None:
        self.total, self.free, self.needed = total, free, needed
        self.update()

    def paintEvent(self, _event) -> None:
        t = themes.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        p.setPen(QPen(QColor(t.border), 1))
        p.setBrush(QColor(t.base))
        p.drawRoundedRect(rect, radius, radius)
        if self.total > 0:
            used = (self.total - self.free) / self.total
            need = min(self.needed / self.total, 1 - used) if self.needed <= self.free else 1 - used
            w = rect.width()
            p.save()
            clip = QRectF(rect)
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.addRoundedRect(clip, radius, radius)
            p.setClipPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.muted))
            p.drawRect(QRectF(rect.left(), rect.top(), w * used, rect.height()))
            seg = QRectF(rect.left() + w * used, rect.top(), w * need, rect.height())
            p.setBrush(QColor(t.danger) if self.needed > self.free else _accent_brush(t, seg))
            p.drawRect(seg)
            p.restore()
        p.end()
