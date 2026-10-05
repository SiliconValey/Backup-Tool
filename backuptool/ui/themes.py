"""Temas visuales: paleta de Qt (estilo Fusion) + una hoja de estilos chica.

Para agregar uno nuevo alcanza con sumar una entrada a THEMES.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    dark: bool
    window: str        # fondo de la ventana
    base: str          # fondo de listas, árbol y campos de texto
    alt_base: str      # filas alternadas
    text: str
    muted: str         # texto secundario
    button: str
    border: str
    accent: str        # selección, botones principales, barra de progreso
    accent_text: str
    danger: str        # avisos (falta espacio, carpeta inexistente)
    warning_bg: str    # franja de "ejecutar como administrador"


SYSTEM_KEY = "system"

THEMES: dict[str, Theme] = {t.key: t for t in (
    Theme("light", "Claro", False,
          window="#f3f4f6", base="#ffffff", alt_base="#f6f8fa", text="#1f2328",
          muted="#656d76", button="#ffffff", border="#d0d7de",
          accent="#2f6fdb", accent_text="#ffffff", danger="#c62828", warning_bg="#fff4d6"),
    Theme("dark", "Oscuro", True,
          window="#1e1f22", base="#2b2d31", alt_base="#303237", text="#e3e5e8",
          muted="#9aa0a6", button="#35373c", border="#45484f",
          accent="#4c8dff", accent_text="#ffffff", danger="#ff6b6b", warning_bg="#4a3b12"),
    Theme("midnight", "Medianoche", True,
          window="#1a2130", base="#212a3b", alt_base="#263045", text="#d8dee9",
          muted="#8e9ab0", button="#2b3549", border="#3b4760",
          accent="#14a39a", accent_text="#ffffff", danger="#f28b82", warning_bg="#3d3520"),
    Theme("sand", "Arena", False,
          window="#f2ede4", base="#fbf8f2", alt_base="#f5f0e6", text="#3b3226",
          muted="#7a6d5c", button="#fbf8f2", border="#d8cdbb",
          accent="#b5651d", accent_text="#ffffff", danger="#b3261e", warning_bg="#f8e2b8"),
)}

THEME_CHOICES: list[tuple[str, str]] = [(SYSTEM_KEY, "Según Windows")] + \
    [(t.key, t.name) for t in THEMES.values()]

_current: Theme | None = None


def resource_path(name: str) -> str:
    """Ruta a un recurso, también dentro del .exe de PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "backuptool", "resources", name)
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", name)


def app_icon() -> QIcon:
    icon = QIcon()
    for name in ("icon.ico", "icon.png"):
        path = resource_path(name)
        if os.path.isfile(path):
            icon.addFile(path)
    return icon


def current() -> Theme:
    """Tema activo; con 'Según Windows' se arma uno a partir de la paleta del sistema."""
    if _current is not None:
        return _current
    pal = QApplication.palette()
    dark = pal.color(QPalette.ColorRole.Window).lightness() < 128
    return THEMES["dark" if dark else "light"]


def _palette(t: Theme) -> QPalette:
    pal = QPalette()
    c = QColor
    R = QPalette.ColorRole
    pal.setColor(R.Window, c(t.window))
    pal.setColor(R.WindowText, c(t.text))
    pal.setColor(R.Base, c(t.base))
    pal.setColor(R.AlternateBase, c(t.alt_base))
    pal.setColor(R.Text, c(t.text))
    pal.setColor(R.Button, c(t.button))
    pal.setColor(R.ButtonText, c(t.text))
    pal.setColor(R.ToolTipBase, c(t.base))
    pal.setColor(R.ToolTipText, c(t.text))
    pal.setColor(R.PlaceholderText, c(t.muted))
    pal.setColor(R.Highlight, c(t.accent))
    pal.setColor(R.HighlightedText, c(t.accent_text))
    pal.setColor(R.Link, c(t.accent))
    pal.setColor(R.BrightText, c(t.danger))
    border = c(t.border)
    pal.setColor(R.Mid, border)
    pal.setColor(R.Dark, border.darker(130))
    pal.setColor(R.Midlight, border.lighter(115))
    pal.setColor(R.Light, c(t.base).lighter(110))
    pal.setColor(R.Shadow, c("#000000"))
    disabled = c(t.muted)
    for role in (R.WindowText, R.Text, R.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    pal.setColor(QPalette.ColorGroup.Disabled, R.Button, c(t.window))
    return pal


INDICATOR = 14  # px lógicos


def _indicator_images(t: Theme) -> dict[str, str]:
    """Dibuja las tildes de las casillas en los colores del tema (Fusion las dibuja
    con un borde casi invisible sobre fondos oscuros). Devuelve rutas para el QSS."""
    folder = os.path.join(tempfile.gettempdir(), "BackupTool_theme", t.key)
    os.makedirs(folder, exist_ok=True)
    paths = {}
    for kind in ("checked", "partial"):
        for scale, suffix in ((1, ""), (2, "@2x")):
            n = INDICATOR * scale
            img = QImage(n, n, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(scale, scale)
            pen = QPen(QColor(t.accent_text), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            if kind == "checked":
                p.drawPolyline([QPointF(3.5, 7.5), QPointF(6, 10), QPointF(10.5, 4.5)])
            else:
                p.drawLine(QPointF(4, 7), QPointF(10, 7))
            p.end()
            path = os.path.join(folder, f"{kind}{suffix}.png")
            img.save(path)
        paths[kind] = os.path.join(folder, f"{kind}.png").replace("\\", "/")
    return paths


def _indicator_qss(t: Theme) -> str:
    try:
        img = _indicator_images(t)
    except OSError:
        return ""
    sel = "QCheckBox::indicator, QTreeView::indicator, QListWidget::indicator"

    def each(state: str) -> str:
        return ", ".join(f"{w}::indicator:{state}" for w in ("QCheckBox", "QTreeView", "QListWidget"))

    hover = QColor(t.accent).lighter(115).name()
    return f"""
{sel} {{ width: {INDICATOR}px; height: {INDICATOR}px; border: 1px solid {QColor(t.muted).name()};
        border-radius: 3px; background: {t.base}; }}
{each("hover")} {{ border-color: {t.accent}; }}
{each("checked")} {{ background: {t.accent}; border-color: {t.accent}; image: url({img["checked"]}); }}
{each("indeterminate")} {{ background: {t.accent}; border-color: {t.accent};
        image: url({img["partial"]}); }}
{each("checked:hover")} {{ background: {hover}; }}
{each("disabled")} {{ border-color: {t.border}; background: {t.window}; }}
"""


def _stylesheet(t: Theme | None) -> str:
    common = """
QGroupBox { font-weight: 600; margin-top: 14px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QPushButton#primary { font-weight: 600; padding: 7px 16px; }
QFrame#adminBanner { border-radius: 6px; }
"""
    if t is None:
        return common + """
QLabel#muted { color: palette(placeholder-text); }
QFrame#adminBanner { border: 1px solid palette(mid); }
"""
    return common + f"""
QLabel#muted {{ color: {t.muted}; }}
QGroupBox {{ border: 1px solid {t.border}; border-radius: 6px; }}
QFrame#adminBanner {{ background: {t.warning_bg}; border: 1px solid {t.border}; }}
QPushButton#primary {{ background: {t.accent}; color: {t.accent_text};
                       border: 1px solid {t.accent}; border-radius: 4px; }}
QPushButton#primary:hover {{ background: {QColor(t.accent).lighter(112).name()}; }}
QPushButton#primary:disabled {{ background: {t.button}; color: {t.muted};
                                border: 1px solid {t.border}; }}
QProgressBar {{ border: 1px solid {t.border}; border-radius: 4px; background: {t.base};
                text-align: center; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}
QTreeView, QListWidget, QPlainTextEdit {{ border: 1px solid {t.border}; }}
QToolTip {{ color: {t.text}; background: {t.base}; border: 1px solid {t.border}; }}
""" + _indicator_qss(t)


def apply_theme(key: str) -> Theme:
    """Aplica el tema a toda la aplicación y lo devuelve."""
    global _current
    app = QApplication.instance()
    hints = app.styleHints()
    if key not in THEMES:
        _current = None
        if hasattr(hints, "unsetColorScheme"):
            hints.unsetColorScheme()
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet(_stylesheet(None))
        return current()
    t = THEMES[key]
    _current = t
    # Qt 6.8+: también pone la barra de título de Windows en modo oscuro/claro
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Dark if t.dark else Qt.ColorScheme.Light)
    app.setPalette(_palette(t))
    app.setStyleSheet(_stylesheet(t))
    return t
