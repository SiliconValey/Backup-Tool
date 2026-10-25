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
    # ---- Opcionales: temas "ricos", con degradés y estilo propio en todos los widgets
    rich: bool = False
    grad: tuple[str, str] | None = None         # botón principal, menús, scroll activo
    bar_grad: tuple[str, str] | None = None     # relleno de la barra de progreso
    chrome_grad: tuple[str, str] | None = None  # barra de menú, encabezados, barra de estado
    chrome_text: str | None = None
    glow: str | None = None                     # borde de foco / hover
    select_bg: str | None = None                # selección en listas y árbol
    select_text: str | None = None
    radius: int = 6
    glossy: bool = False                        # degradé con "brillo" a la mitad (estilo Aero)


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
    # Dashboard violeta con barra lateral magenta y acentos naranja/rosa
    Theme("neon", "Neón", True,
          window="#1c0c4f", base="#24105f", alt_base="#2a1468", text="#ffffff",
          muted="#b9a7e6", button="#341878", border="#4a2a9a",
          accent="#ff2e93", accent_text="#ffffff", danger="#ff5470", warning_bg="#5a1d5e",
          rich=True, grad=("#ff2e93", "#8a2be2"), bar_grad=("#ff6a00", "#ff2e93"),
          chrome_grad=("#e0219a", "#6a1bd6"), chrome_text="#ffffff", glow="#ff5fb1",
          select_bg="#7a2fd6", select_text="#ffffff", radius=8),
    # Paneles de vidrio azul noche con brillo azul-violeta
    Theme("glass", "Cristal", True,
          window="#0b1030", base="#141b45", alt_base="#18204f", text="#e6ecff",
          muted="#8f9bd0", button="#1d2760", border="#2f3c86",
          accent="#5b7cff", accent_text="#ffffff", danger="#ff6b8a", warning_bg="#3a2a5e",
          rich=True, grad=("#3d7bff", "#9b5cff"), bar_grad=("#3d7bff", "#9b5cff"),
          chrome_grad=("#161f52", "#0e1438"), chrome_text="#cfd8ff", glow="#7f8cff",
          select_bg="#3b4fc4", select_text="#ffffff", radius=10),
    # Azul vidriado de Windows Vista: botones con brillo y selección celeste
    Theme("aero", "Aero", False,
          window="#dfeaf6", base="#ffffff", alt_base="#f3f8fd", text="#1e2b3a",
          muted="#5c6f84", button="#eef4fb", border="#a9c2dd",
          accent="#2f7fd8", accent_text="#ffffff", danger="#c42b1c", warning_bg="#fff1c2",
          rich=True, grad=("#5aa7ef", "#1f6cc4"), bar_grad=("#5fc4f2", "#1f8fd6"),
          chrome_grad=("#fbfdff", "#d3e3f5"), chrome_text="#1e2b3a", glow="#3d8fe0",
          select_bg="#cde6fb", select_text="#10243a", radius=4, glossy=True),
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
    pal.setColor(R.Highlight, c(t.select_bg or t.accent))
    pal.setColor(R.HighlightedText, c(t.select_text or t.accent_text))
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


def _arrow_images(t: Theme) -> dict[str, str]:
    """Flechas para combos, spinbox y encabezados: al estilizar esos widgets con QSS,
    Qt deja de dibujar las flechas nativas y hay que darle una imagen."""
    folder = os.path.join(tempfile.gettempdir(), "BackupTool_theme", t.key)
    os.makedirs(folder, exist_ok=True)
    shapes = {"down": [QPointF(2, 4), QPointF(6, 8), QPointF(10, 4)],
              "up": [QPointF(2, 8), QPointF(6, 4), QPointF(10, 8)]}
    color = t.chrome_text or t.text
    paths = {}
    for kind, pts in shapes.items():
        for scale, suffix in ((1, ""), (2, "@2x")):
            img = QImage(12 * scale, 12 * scale, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(scale, scale)
            pen = QPen(QColor(color), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPolyline(pts)
            p.end()
            img.save(os.path.join(folder, f"arrow_{kind}{suffix}.png"))
        paths[kind] = os.path.join(folder, f"arrow_{kind}.png").replace("\\", "/")
    return paths


def _lighter(color: str, factor: int) -> str:
    return QColor(color).lighter(factor).name()


def _darker(color: str, factor: int) -> str:
    return QColor(color).darker(factor).name()


def _gradient(colors: tuple[str, str], horizontal: bool, glossy: bool = False) -> str:
    a, b = colors
    x2, y2 = (1, 0) if horizontal else (0, 1)
    if glossy:   # mitad de arriba más clara y corte marcado, como los botones de Vista
        return (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {_lighter(a, 125)}, "
                f"stop:0.48 {a}, stop:0.52 {b}, stop:1 {_lighter(b, 115)})")
    return f"qlineargradient(x1:0, y1:0, x2:{x2}, y2:{y2}, stop:0 {a}, stop:1 {b})"


def _rich_qss(t: Theme) -> str:
    """Hoja de estilos completa para los temas con degradés (Neón, Cristal, Aero)."""
    try:
        arrow = _arrow_images(t)
    except OSError:
        arrow = {"down": "", "up": ""}
    r = t.radius
    grad = t.grad or (t.accent, t.accent)
    accent_bg = _gradient(grad, horizontal=not t.glossy, glossy=t.glossy)
    accent_hover = _gradient((_lighter(grad[0], 112), _lighter(grad[1], 112)),
                             horizontal=not t.glossy, glossy=t.glossy)
    bar = _gradient(t.bar_grad or grad, horizontal=True)
    if t.glossy:
        bar = _gradient(t.bar_grad or grad, horizontal=False, glossy=True)
    chrome = _gradient(t.chrome_grad or (t.window, t.window), horizontal=not t.glossy)
    # Vertical siempre: con uno horizontal cada columna repetiría el degradé
    header = _gradient(t.chrome_grad or (t.window, t.window), horizontal=False)
    chrome_text = t.chrome_text or t.text
    glow = t.glow or t.accent
    if t.glossy:
        button = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, "
                  f"stop:0.48 {t.button}, stop:0.52 {_darker(t.button, 106)}, "
                  f"stop:1 {_darker(t.button, 102)})")
        button_hover = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, "
                        f"stop:0.48 #e8f4fd, stop:0.52 #c4e3fa, stop:1 #d9eefc)")
    else:
        button = _gradient((_lighter(t.button, 118), t.button), horizontal=False)
        button_hover = _gradient((_lighter(t.button, 135), _lighter(t.button, 110)),
                                 horizontal=False)
    pressed = _darker(t.button, 115)
    hover_row = QColor(glow)
    hover_row.setAlpha(40)
    hover_rgba = f"rgba({hover_row.red()}, {hover_row.green()}, {hover_row.blue()}, 40)"

    return f"""
QMainWindow, QDialog, QMessageBox, QInputDialog {{ background: {t.window}; }}
QWidget {{ color: {t.text}; }}

/* ---- Barra de menú y menús */
QMenuBar {{ background: {chrome}; color: {chrome_text}; padding: 2px 4px;
            border-bottom: 1px solid {t.border}; }}
QMenuBar::item {{ background: transparent; color: {chrome_text}; padding: 4px 10px;
                  border-radius: {r}px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {accent_bg}; color: {t.accent_text}; }}
QMenu {{ background: {t.base}; color: {t.text}; border: 1px solid {glow};
         border-radius: {r}px; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 20px; border-radius: {max(r - 2, 2)}px; }}
QMenu::item:selected {{ background: {accent_bg}; color: {t.accent_text}; }}
QMenu::item:disabled {{ color: {t.muted}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}

/* ---- Botones */
QPushButton, QToolButton {{ background: {button}; color: {t.text};
        border: 1px solid {t.border}; border-radius: {r}px; padding: 5px 12px; }}
QPushButton:hover, QToolButton:hover {{ background: {button_hover}; border-color: {glow}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {pressed}; }}
QPushButton:focus {{ border-color: {glow}; }}
QPushButton:disabled, QToolButton:disabled {{ background: {t.window}; color: {t.muted};
        border-color: {t.border}; }}
QToolButton:checked {{ background: {accent_bg}; color: {t.accent_text}; border-color: {glow}; }}
QPushButton#primary {{ background: {accent_bg}; color: {t.accent_text};
        border: 1px solid {glow}; border-radius: {r}px; padding: 7px 18px; }}
QPushButton#primary:hover {{ background: {accent_hover}; }}
QPushButton#primary:pressed {{ background: {_darker(grad[1], 110)}; }}
QPushButton#primary:disabled {{ background: {t.button}; color: {t.muted}; border-color: {t.border}; }}

/* ---- Campos de texto, combos y spinbox */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ background: {t.base}; color: {t.text};
        border: 1px solid {t.border}; border-radius: {r}px; padding: 4px 6px;
        selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {_lighter(t.border, 125)}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {glow}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {t.muted};
        background: {t.window}; }}
QComboBox {{ padding-right: 24px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
        width: 22px; border: none; }}
QComboBox::down-arrow {{ image: url({arrow["down"]}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t.base}; color: {t.text}; border: 1px solid {glow};
        selection-background-color: {t.select_bg or t.accent};
        selection-color: {t.select_text or t.accent_text}; outline: 0; padding: 2px; }}
QSpinBox {{ padding-right: 20px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 18px;
        border: none; background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {hover_rgba}; }}
QSpinBox::up-arrow {{ image: url({arrow["up"]}); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({arrow["down"]}); width: 10px; height: 10px; }}

/* ---- Barra de progreso */
QProgressBar {{ background: {t.base}; color: {t.text}; border: 1px solid {t.border};
        border-radius: {r}px; text-align: center; min-height: 18px; font-weight: 600; }}
QProgressBar::chunk {{ background: {bar}; border-radius: {max(r - 1, 2)}px; margin: 1px; }}

/* ---- Listas, árbol y encabezados */
QTreeView, QListWidget {{ background: {t.base}; alternate-background-color: {t.alt_base};
        border: 1px solid {t.border}; border-radius: {r}px; outline: 0; }}
QTreeView:focus, QListWidget:focus {{ border-color: {glow}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {header}; color: {chrome_text}; border: none;
        border-right: 1px solid {t.border}; border-bottom: 1px solid {t.border};
        padding: 5px 8px; font-weight: 600; }}
QHeaderView::section:hover {{ background: {accent_bg}; color: {t.accent_text}; }}
QHeaderView::up-arrow {{ image: url({arrow["up"]}); width: 10px; height: 10px;
        subcontrol-position: center right; padding-right: 4px; }}
QHeaderView::down-arrow {{ image: url({arrow["down"]}); width: 10px; height: 10px;
        subcontrol-position: center right; padding-right: 4px; }}

/* ---- Grupos, paneles y separadores */
QGroupBox {{ background: {t.alt_base if t.dark else t.base}; border: 1px solid {t.border};
        border-radius: {r}px; }}
QGroupBox::title {{ color: {glow if t.dark else _darker(t.accent, 115)}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QSplitter::handle {{ background: {t.window}; }}
QSplitter::handle:hover {{ background: {glow}; }}
QFrame#adminBanner {{ background: {t.warning_bg}; border: 1px solid {glow}; }}

/* ---- Barras de desplazamiento */
QScrollBar:vertical {{ background: {t.window}; width: 11px; margin: 0; border: none; }}
QScrollBar:horizontal {{ background: {t.window}; height: 11px; margin: 0; border: none; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 5px; min-height: 30px;
        margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 5px; min-width: 30px;
        margin: 2px; }}
QScrollBar::handle:hover {{ background: {_gradient(grad, horizontal=False)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---- Pestañas y deslizadores (por si se agregan en el rediseño) */
QTabWidget::pane {{ border: 1px solid {t.border}; border-radius: {r}px; top: -1px; }}
QTabBar::tab {{ background: {t.button}; color: {t.muted}; border: 1px solid {t.border};
        padding: 6px 14px; border-top-left-radius: {r}px; border-top-right-radius: {r}px;
        margin-right: 2px; }}
QTabBar::tab:selected {{ background: {accent_bg}; color: {t.accent_text}; border-color: {glow}; }}
QTabBar::tab:hover:!selected {{ color: {t.text}; border-color: {glow}; }}
QSlider::groove:horizontal {{ height: 6px; background: {t.base}; border: 1px solid {t.border};
        border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {bar}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t.accent_text}; border: 2px solid {t.accent};
        width: 14px; margin: -6px 0; border-radius: 8px; }}

/* ---- Barra de estado y globos de ayuda */
QStatusBar {{ background: {chrome}; color: {chrome_text}; border-top: 1px solid {t.border}; }}
QStatusBar QLabel {{ color: {chrome_text}; }}
QToolTip {{ color: {t.text}; background: {t.base}; border: 1px solid {glow};
        border-radius: {r}px; padding: 4px 6px; }}
QLabel#muted {{ color: {t.muted}; }}
"""


def _stylesheet(t: Theme | None) -> str:
    common = """
QGroupBox { font-weight: 600; margin-top: 14px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QPushButton#primary { font-weight: 600; padding: 7px 16px; }
QFrame#adminBanner { border-radius: 6px; }
QLabel#pageTitle { font-size: 17pt; font-weight: 700; }
QLabel#sectionTitle { font-size: 11pt; font-weight: 700; }
QFrame#warnBox { border-radius: 6px; }
QPushButton#nav { padding: 7px 18px; min-width: 90px; }
"""
    if t is None:
        return common + """
QLabel#muted, QLabel#pageSubtitle { color: palette(placeholder-text); }
QFrame#adminBanner, QFrame#warnBox { border: 1px solid palette(mid); }
QFrame#navBar { border-top: 1px solid palette(mid); }
QPushButton#primary { background: palette(highlight); color: palette(highlighted-text);
                      border: 1px solid palette(highlight); border-radius: 4px; }
QPushButton#primary:disabled { background: palette(button); color: palette(placeholder-text);
                               border: 1px solid palette(mid); }
"""
    return common + f"""
QLabel#muted, QLabel#pageSubtitle {{ color: {t.muted}; }}
QFrame#navBar {{ border-top: 1px solid {t.border}; }}
QFrame#warnBox {{ background: {t.warning_bg}; border: 1px solid {t.border}; }}
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
""" + (_rich_qss(t) if t.rich else "") + _indicator_qss(t)


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
