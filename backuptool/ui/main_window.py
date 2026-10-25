"""Ventana principal de BackupTool: un asistente de seis pasos.

    1 Origen  →  2 Qué copiar  →  3 Revisar  →  4 Destino  →  5 Copiando  →  6 Listo

Pensado para respaldar los datos de una PC antes de reinstalar Windows.
"""

from __future__ import annotations

import html
import os
import shutil
import time

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QImageReader, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QToolButton,
                               QTreeView, QVBoxLayout, QWidget)

from .. import APP_NAME, APP_VERSION
from ..core import categories as cats
from ..core.copier import CopyOptions, CopyProgress, default_backup_name, required_space
from ..core.models import CopyResult, FoundItem, ItemKind, ScanStats
from ..core.scanner import ScanOptions
from ..core.winutils import (IS_WINDOWS, filesystem_of, format_count, format_size, is_admin,
                             list_drives, open_in_explorer, relaunch_as_admin, system_drive,
                             users_root)
from . import themes
from .file_model import (COL_COUNT, COL_DATE, COL_NAME, COL_SIZE, ITEM_ROLE, LEVEL_ITEM,
                         LEVEL_ROLE, FoundItemsModel, FoundItemsProxy)
from .icons import icon
from .widgets import OptionCard, SpaceBar, StatTile, StepHeader
from .workers import BackupWorker, ScanWorker, start_in_thread

STEPS = ["Origen", "Qué copiar", "Revisar", "Destino", "Copiando", "Listo"]
P_ORIGIN, P_WHAT, P_REVIEW, P_DEST, P_COPY, P_DONE = range(6)
LAST_NAVIGABLE = P_DEST      # a "Copiando" y "Listo" no se vuelve con la barra de pasos

CATEGORY_ICONS = {
    "images": "images", "audio": "audio", "video": "video", "documents": "documents",
    "mail": "mail", "security": "security", "saved_games": "saved_games",
}
CATEGORY_SUBTITLES = {
    "images": "Fotos, capturas y RAW de cámaras",
    "audio": "Música, grabaciones y notas de voz",
    "video": "Videos y filmaciones",
    "documents": "Office, PDF, texto y libros",
    "mail": "Outlook (.pst), correos y contactos",
    "security": "KeePass, certificados y claves",
    "saved_games": "Carpetas «Saved Games»",
}


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def _muted(text: str = "") -> QLabel:
    return _label(text, "muted")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — Backup antes de reinstalar")
        self.resize(1180, 820)
        self.setMinimumSize(980, 700)
        self.settings = QSettings(APP_NAME, APP_NAME)

        self._scan_worker: ScanWorker | None = None
        self._backup_worker: BackupWorker | None = None
        self._thread = None
        self._scanned_roots: list[str] = []
        self._has_results = False      # hubo una búsqueda y sus opciones no cambiaron
        self._copy_started = 0.0
        self._scan_started = 0.0
        self._closing = False
        self._last_result: CopyResult | None = None

        self.model = FoundItemsModel(self)
        # El proxy se conecta al modelo sólo mientras se filtra (ver _set_view_model)
        self.proxy = FoundItemsProxy(self)
        self.model.selectionTotalsChanged.connect(self._on_totals_changed)

        self.setWindowIcon(themes.app_icon())
        self._theme_key = self.settings.value("theme", themes.SYSTEM_KEY)
        themes.apply_theme(self._theme_key)
        self._build_ui()
        self._build_menu()
        self._load_settings()
        self._refresh_drives()
        self._go_to(P_ORIGIN)

    # ================================================================ armado
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 10, 18, 10)
        outer.setSpacing(8)

        if IS_WINDOWS and not is_admin():
            outer.addWidget(self._build_admin_banner())

        self.header = StepHeader(STEPS)
        self.header.stepClicked.connect(self._on_step_clicked)
        outer.addWidget(self.header)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._page_origin())
        self.pages.addWidget(self._page_what())
        self.pages.addWidget(self._page_review())
        self.pages.addWidget(self._page_dest())
        self.pages.addWidget(self._page_copy())
        self.pages.addWidget(self._page_done())
        outer.addWidget(self.pages, 1)
        outer.addWidget(self._build_nav())
        self.setCentralWidget(central)

        self.status_label = QLabel("Listo.")
        self.statusBar().addWidget(self.status_label, 1)

    def _build_menu(self) -> None:
        bar = self.menuBar()
        m_file = bar.addMenu("&Archivo")
        act_new = QAction("&Nuevo backup", self)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(self._new_backup)
        m_file.addAction(act_new)
        m_file.addSeparator()
        act_quit = QAction("&Salir", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_view = bar.addMenu("&Ver")
        m_theme = m_view.addMenu("&Tema")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for key, name in themes.THEME_CHOICES:
            act = QAction(name, self, checkable=True)
            act.setChecked(key == self._theme_key)
            act.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            group.addAction(act)
            m_theme.addAction(act)
            self.theme_actions[key] = act
            if key == themes.SYSTEM_KEY:
                m_theme.addSeparator()
        act_log = QAction("&Registro de la copia", self, checkable=True)
        act_log.toggled.connect(lambda on: self.log_view.setVisible(on))
        m_view.addAction(act_log)
        self.act_log = act_log

        m_help = bar.addMenu("A&yuda")
        act_about = QAction("&Acerca de BackupTool", self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

    def _build_admin_banner(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("adminBanner")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 6, 10, 6)
        lbl = QLabel("⚠  La app no se está ejecutando como administrador: los <b>drivers</b>, "
                     "las <b>claves Wi-Fi</b> y los perfiles de otros usuarios no se van a poder respaldar.")
        lbl.setWordWrap(True)
        btn = QPushButton("Reiniciar como administrador")
        btn.clicked.connect(self._restart_as_admin)
        lay.addWidget(lbl, 1)
        lay.addWidget(btn)
        return frame

    def _build_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("navBar")
        lay = QHBoxLayout(nav)
        lay.setContentsMargins(0, 10, 0, 0)
        self.btn_back = QPushButton("‹  Atrás")
        self.btn_back.setObjectName("nav")
        self.btn_back.clicked.connect(self._go_back)
        self.nav_hint = _muted("")
        self.btn_next = QPushButton("Siguiente  ›")
        self.btn_next.setObjectName("primary")
        self.btn_next.setMinimumWidth(170)
        self.btn_next.clicked.connect(self._go_next)
        lay.addWidget(self.btn_back)
        lay.addWidget(self.nav_hint, 1)
        lay.addWidget(self.btn_next)
        return nav

    @staticmethod
    def _page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 6, 4, 0)
        lay.setSpacing(8)
        lay.addWidget(_label(title, "pageTitle"))
        if subtitle:
            lay.addWidget(_label(subtitle, "pageSubtitle"))
        lay.addSpacing(6)
        return page, lay

    # ------------------------------------------------------------ 1. Origen
    def _page_origin(self) -> QWidget:
        page, lay = self._page(
            "¿Dónde están tus datos?",
            "Se recorren los perfiles de usuario (fotos, escritorio, documentos…). Tildá otras "
            "unidades si también tienen datos tuyos, o agregá carpetas sueltas.")
        self.roots_list = QListWidget()
        self.roots_list.setIconSize(QSize(28, 28))
        self.roots_list.setSpacing(3)
        self.roots_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.roots_list.itemChanged.connect(lambda _it: self._mark_scan_dirty())
        lay.addWidget(self.roots_list, 1)
        row = QHBoxLayout()
        btn_add = QPushButton("Agregar carpeta…")
        btn_add.clicked.connect(self._add_root_folder)
        btn_del = QPushButton("Quitar seleccionadas")
        btn_del.clicked.connect(self._remove_root)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_muted("Para un disco entero agregá su raíz (por ejemplo D:\\). "
                             "Windows, Archivos de programa, ProgramData y AppData no se recorren: "
                             "no tienen datos personales y se reinstalan solos. Los marcadores de "
                             "los navegadores, que viven en AppData, se buscan aparte."))
        self._populate_roots()
        return page

    def _populate_roots(self) -> None:
        self.roots_list.blockSignals(True)
        self.roots_list.clear()
        self._add_root_item(users_root(), "Perfiles de usuario", checked=True)
        sysdrive = system_drive().upper()
        for d in list_drives():
            if d.root.upper() == sysdrive:
                continue
            self._add_root_item(d.root, d.describe(), checked=False, removable=d.is_removable)
        self.roots_list.blockSignals(False)

    def _add_root_item(self, path: str, label: str = "", checked: bool = True,
                       removable: bool = False) -> None:
        for i in range(self.roots_list.count()):
            it = self.roots_list.item(i)
            if os.path.normcase(it.data(Qt.ItemDataRole.UserRole)) == os.path.normcase(path):
                it.setCheckState(Qt.CheckState.Checked)
                return
        text = f"{path}\n{label}" if label else path
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, path)
        kind = "usb" if removable else ("drive" if len(path) <= 3 else "folder")
        item.setData(Qt.ItemDataRole.UserRole + 1, kind)
        item.setIcon(icon(kind, themes.current().glow or themes.current().accent))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        item.setToolTip(path)
        item.setSizeHint(QSize(0, 48))
        self.roots_list.addItem(item)

    def _add_root_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Agregar carpeta o unidad a recorrer")
        if folder:
            self._add_root_item(os.path.normpath(folder), "Carpeta agregada")
            self._mark_scan_dirty()

    def _remove_root(self) -> None:
        for item in self.roots_list.selectedItems():
            self.roots_list.takeItem(self.roots_list.row(item))
        self._mark_scan_dirty()

    def _checked_roots(self) -> list[str]:
        return [self.roots_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.roots_list.count())
                if self.roots_list.item(i).checkState() == Qt.CheckState.Checked]

    # -------------------------------------------------------- 2. Qué copiar
    def _page_what(self) -> QWidget:
        page, lay = self._page("¿Qué querés respaldar?",
                               "Tocá una tarjeta para incluirla o sacarla del backup.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(_label("Archivos personales", "sectionTitle"))
        head.addStretch(1)
        for text, value in (("Todas", True), ("Ninguna", False)):
            b = QToolButton()
            b.setText(text)
            b.clicked.connect(lambda _=False, v=value: self._set_all_categories(v))
            head.addWidget(b)
        bl.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.cat_checks: dict[str, OptionCard] = {}
        for n, cat in enumerate(cats.ALL_CATEGORIES):
            card = OptionCard(CATEGORY_ICONS[cat.key], cat.label, CATEGORY_SUBTITLES[cat.key])
            card.setToolTip(cat.description)
            card.toggled.connect(lambda _on: self._mark_scan_dirty())
            self.cat_checks[cat.key] = card
            grid.addWidget(card, n // 3, n % 3)
        bl.addLayout(grid)

        bl.addSpacing(6)
        bl.addWidget(_label("Navegadores y sistema", "sectionTitle"))
        grid2 = QGridLayout()
        grid2.setSpacing(10)
        self.cb_bookmarks = OptionCard("bookmarks", "Marcadores",
                                       "Chrome, Edge, Firefox, Brave, Opera… de todos los usuarios")
        self.cb_bookmarks.toggled.connect(lambda _on: self._mark_scan_dirty())
        self.cb_drivers = OptionCard("drivers", "Drivers de terceros",
                                     "Para reinstalarlos después (requiere administrador)")
        self.cb_drivers.setChecked(IS_WINDOWS)
        self.cb_drivers.toggled.connect(lambda _on: self._mark_scan_dirty())
        self.cb_wifi = OptionCard("wifi", "Redes Wi-Fi", "Perfiles guardados, para no tener que reconfigurarlos")
        self.cb_wifi.setChecked(IS_WINDOWS)
        self.cb_programs = OptionCard("programs", "Programas instalados",
                                      "Lista en CSV para saber qué reinstalar")
        self.cb_programs.setChecked(IS_WINDOWS)
        for i, card in enumerate((self.cb_bookmarks, self.cb_drivers, self.cb_wifi, self.cb_programs)):
            grid2.addWidget(card, i // 3, i % 3)
        bl.addLayout(grid2)

        bl.addSpacing(6)
        bl.addWidget(_label("Opciones", "sectionTitle"))
        opts = QGridLayout()
        opts.setHorizontalSpacing(16)
        self.cb_wifi_keys = QCheckBox("Incluir las contraseñas Wi-Fi (quedan en texto plano en el backup)")
        self.cb_wifi.toggled.connect(self.cb_wifi_keys.setEnabled)
        opts.addWidget(self.cb_wifi_keys, 0, 0, 1, 3)
        self.cb_skip_cloud = QCheckBox("Omitir archivos de OneDrive que están sólo en la nube")
        self.cb_skip_cloud.setChecked(True)
        self.cb_skip_cloud.setToolTip("Leerlos obligaría a descargarlos; ya están a salvo en la nube")
        self.cb_skip_cloud.toggled.connect(lambda _on: self._mark_scan_dirty())
        opts.addWidget(self.cb_skip_cloud, 1, 0, 1, 3)
        opts.addWidget(QLabel("Ignorar imágenes menores a"), 2, 0)
        self.spin_min_img = QSpinBox()
        self.spin_min_img.setRange(0, 10_000)
        self.spin_min_img.setSuffix(" KB")
        self.spin_min_img.setValue(cats.IMAGES.default_min_kb)
        self.spin_min_img.setToolTip("Evita iconos y miniaturas")
        self.spin_min_img.valueChanged.connect(lambda _v: self._mark_scan_dirty())
        opts.addWidget(self.spin_min_img, 2, 1)
        btn_excl = QPushButton("Carpetas excluidas…")
        btn_excl.clicked.connect(self._edit_exclusions)
        opts.addWidget(btn_excl, 2, 2, Qt.AlignmentFlag.AlignLeft)
        opts.setColumnStretch(3, 1)
        bl.addLayout(opts)
        bl.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        return page

    def _set_all_categories(self, value: bool) -> None:
        for card in self.cat_checks.values():
            card.setChecked(value)

    def _edit_exclusions(self) -> None:
        current = "\n".join(sorted(self._excluded_dirs()))
        text, ok = QInputDialog.getMultiLineText(
            self, "Carpetas excluidas",
            "Nombres de carpeta que no se recorren, uno por línea.\n"
            "Las de sistema (Windows, Program Files, ProgramData, Recovery…) se excluyen "
            "sólo en la raíz de cada unidad; el resto, en cualquier nivel.", current)
        if ok:
            names = {t.strip().casefold() for t in text.splitlines() if t.strip()}
            defaults = set(cats.DEFAULT_EXCLUDED_DIRS)
            # Se guarda la diferencia con los valores por defecto: así, si una versión
            # nueva agrega exclusiones, se aplican sin pisar lo que eligió el usuario.
            self.settings.setValue("excluded_added", sorted(names - defaults))
            self.settings.setValue("excluded_removed", sorted(defaults - names))
            self.settings.remove("excluded_dirs")
            self._mark_scan_dirty()

    def _excluded_dirs(self) -> set[str]:
        def as_list(value) -> list[str]:
            if not value:
                return []
            return [value] if isinstance(value, str) else list(value)

        defaults = set(cats.DEFAULT_EXCLUDED_DIRS)
        legacy = as_list(self.settings.value("excluded_dirs"))
        if legacy:   # formato viejo: la lista completa
            legacy_set = {n.casefold() for n in legacy}
            added, removed = legacy_set - defaults, defaults - legacy_set
        else:
            added = set(as_list(self.settings.value("excluded_added")))
            removed = set(as_list(self.settings.value("excluded_removed")))
        return (defaults - removed) | added

    # ----------------------------------------------------------- 3. Revisar
    def _page_review(self) -> QWidget:
        page, lay = self._page("Revisá lo que se encontró",
                               "Destildá lo que no quieras llevarte. Doble clic abre el archivo.")
        # Franja de progreso de la búsqueda
        self.scan_strip = QFrame()
        sl = QHBoxLayout(self.scan_strip)
        sl.setContentsMargins(0, 0, 0, 0)
        self.scan_bar = QProgressBar()
        self.scan_bar.setRange(0, 0)
        self.scan_bar.setTextVisible(False)
        self.scan_bar.setMaximumHeight(10)
        self.scan_text = _muted("")
        self.btn_cancel_scan = QPushButton("Detener búsqueda")
        self.btn_cancel_scan.clicked.connect(self._cancel_scan)
        col = QVBoxLayout()
        col.addWidget(self.scan_text)
        col.addWidget(self.scan_bar)
        sl.addLayout(col, 1)
        sl.addWidget(self.btn_cancel_scan)
        lay.addWidget(self.scan_strip)

        top = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filtrar por nombre o carpeta…")
        self.filter_edit.setClearButtonEnabled(True)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.filter_edit.textChanged.connect(lambda _: self._filter_timer.start())
        top.addWidget(self.filter_edit, 1)
        self.btn_check_all = QPushButton("Marcar todo")
        self.btn_check_all.clicked.connect(lambda: self._check_visible(True))
        self.btn_uncheck_all = QPushButton("Desmarcar todo")
        self.btn_uncheck_all.clicked.connect(lambda: self._check_visible(False))
        top.addWidget(self.btn_check_all)
        top.addWidget(self.btn_uncheck_all)
        self.tree = QTreeView()
        btn_expand = QToolButton()
        btn_expand.setText("Expandir")
        btn_expand.clicked.connect(lambda: self.tree.expandToDepth(0))
        btn_collapse = QToolButton()
        btn_collapse.setText("Contraer")
        btn_collapse.clicked.connect(self.tree.collapseAll)
        top.addWidget(btn_expand)
        top.addWidget(btn_collapse)
        lay.addLayout(top)

        self.tree.setUniformRowHeights(True)     # clave para listas enormes
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.doubleClicked.connect(self._open_index)
        self._set_view_model(self.model)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(COL_NAME, 320)
        header.resizeSection(COL_COUNT, 80)
        header.resizeSection(COL_SIZE, 90)
        header.resizeSection(COL_DATE, 130)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(self._build_preview())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([820, 250])
        lay.addWidget(splitter, 1)

        self.summary_label = _muted("Todavía no se buscó nada.")
        self.scan_info = _muted("")
        lay.addWidget(self.summary_label)
        lay.addWidget(self.scan_info)
        return page

    def _build_preview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 0, 0, 0)
        lay.addWidget(_label("Vista previa", "sectionTitle"))
        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setMinimumSize(QSize(220, 200))
        self.preview_image.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preview_info = QLabel("Seleccioná un archivo para ver sus datos.")
        self.preview_info.setWordWrap(True)
        self.preview_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview_info.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.preview_image)
        lay.addWidget(self.preview_info, 1)
        self._image_formats = {bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()}
        return w

    def _set_view_model(self, model) -> None:
        """Sin filtro el árbol usa el modelo directo (mucho más rápido con grupos
        grandes expandidos); el proxy de filtrado sólo se usa mientras hay texto."""
        if self.tree.model() is model:
            return
        old_sel = self.tree.selectionModel()
        self.tree.setModel(model)
        if old_sel is not None:
            old_sel.deleteLater()   # setModel no libera el selectionModel anterior
        if model is not self.proxy:
            self.proxy.setSourceModel(None)
        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        header = self.tree.header()
        self.tree.sortByColumn(header.sortIndicatorSection(), header.sortIndicatorOrder())

    def _apply_filter(self) -> None:
        text = self.filter_edit.text().strip()
        if text:
            if self.proxy.sourceModel() is None:
                self.proxy.setSourceModel(self.model)
            self.proxy.set_filter_text(text)
            self._set_view_model(self.proxy)
            self.tree.expandToDepth(1)
            self.btn_check_all.setText("Marcar visibles")
            self.btn_uncheck_all.setText("Desmarcar visibles")
        else:
            self.proxy.set_filter_text("")
            self._set_view_model(self.model)
            self.tree.expandToDepth(0)
            self.btn_check_all.setText("Marcar todo")
            self.btn_uncheck_all.setText("Desmarcar todo")

    def _check_visible(self, checked: bool) -> None:
        """Sin filtro marca todo; con filtro, sólo los archivos que se ven."""
        if self.tree.model() is not self.proxy:
            self.model.set_all_checked(checked)
            return
        leaves = []
        stack = [self.proxy.index(r, 0) for r in range(self.proxy.rowCount())]
        while stack:
            idx = stack.pop()
            if idx.data(LEVEL_ROLE) == LEVEL_ITEM:
                leaves.append(self.proxy.mapToSource(idx))
            else:
                stack.extend(self.proxy.index(r, 0, idx) for r in range(self.proxy.rowCount(idx)))
        self.model.set_checked_many(leaves, checked)

    def _selected_source_indexes(self):
        rows = self.tree.selectionModel().selectedRows(COL_NAME)
        if self.tree.model() is self.proxy:
            return [self.proxy.mapToSource(i) for i in rows]
        return rows

    def _tree_menu(self, pos) -> None:
        idx = self.tree.indexAt(pos)
        menu = QMenu(self)
        item: FoundItem | None = idx.data(ITEM_ROLE) if idx.isValid() else None
        if item is not None:
            act_open = QAction("Abrir", self)
            act_open.triggered.connect(lambda: self._open_index(idx))
            act_show = QAction("Mostrar en el Explorador", self)
            act_show.triggered.connect(lambda: open_in_explorer(item.path))
            menu.addAction(act_open)
            menu.addAction(act_show)
            menu.addSeparator()
        sel = self._selected_source_indexes()
        if sel:
            act_check = QAction(f"Marcar seleccionados ({len(sel)})", self)
            act_check.triggered.connect(lambda: self.model.set_checked_many(sel, True))
            act_uncheck = QAction(f"Desmarcar seleccionados ({len(sel)})", self)
            act_uncheck.triggered.connect(lambda: self.model.set_checked_many(sel, False))
            menu.addAction(act_check)
            menu.addAction(act_uncheck)
        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _open_index(self, idx) -> None:
        item: FoundItem | None = idx.data(ITEM_ROLE)
        if item is None:
            return
        if item.kind is ItemKind.FILE:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.path))
        else:
            open_in_explorer(item.path)

    def _on_current_changed(self, current, _previous) -> None:
        item: FoundItem | None = current.data(ITEM_ROLE) if current.isValid() else None
        self.preview_image.clear()
        if item is None:
            self.preview_info.setText(f"<b>{_esc(current.data() or '')}</b><br>"
                                      f"{_esc(current.data(Qt.ItemDataRole.ToolTipRole) or '')}"
                                      if current.isValid() else "")
            return
        lines = [f"<b>{_esc(item.name)}</b>"]
        if item.kind is ItemKind.FILE:
            lines.append(f"{item.category} · {item.group}")
            lines.append(f"Tamaño: {format_size(item.size)}")
            if item.mtime:
                lines.append("Modificado: " + time.strftime("%d/%m/%Y %H:%M", time.localtime(item.mtime)))
        elif item.kind is ItemKind.BOOKMARK:
            lines.append(f"Navegador: {_esc(item.extra.get('browser', ''))}")
            lines.append(f"Usuario: {_esc(item.extra.get('user', ''))} · perfil "
                         f"{_esc(item.extra.get('profile', ''))}")
            if item.extra.get("count") is not None:
                lines.append(f"Marcadores: {item.extra['count']}")
            lines.append("Se copia el archivo original y se exporta a HTML.")
        elif item.kind is ItemKind.DRIVER:
            lines.append(f"Clase: {_esc(item.extra.get('class', ''))}")
            lines.append(f"Fabricante: {_esc(item.extra.get('provider', ''))}")
            if item.extra.get("version"):
                lines.append(f"Versión: {_esc(item.extra['version'])}")
        lines.append(f"<br><span style='font-size:small'>{_esc(item.path)}</span>")
        self.preview_info.setText("<br>".join(lines))

        ext = os.path.splitext(item.path)[1].lower().lstrip(".")
        if item.kind is ItemKind.FILE and ext in self._image_formats and item.size < 80 * 1024 * 1024:
            reader = QImageReader(item.path)
            reader.setAutoTransform(True)
            size = reader.size()
            box = self.preview_image.size() - QSize(8, 8)
            if size.isValid():
                reader.setScaledSize(size.scaled(box, Qt.AspectRatioMode.KeepAspectRatio))
            img = reader.read()
            if not img.isNull():
                self.preview_image.setPixmap(QPixmap.fromImage(img))
                return
        self.preview_image.setText("Sin vista previa")

    # ----------------------------------------------------------- 4. Destino
    def _page_dest(self) -> QWidget:
        page, lay = self._page("¿Dónde guardamos el backup?",
                               "Usá un disco externo o un pendrive: el disco del sistema se "
                               "va a formatear al reinstalar.")
        row = QHBoxLayout()
        self.drives_list = QListWidget()
        self.drives_list.setIconSize(QSize(28, 28))
        self.drives_list.setSpacing(3)
        self.drives_list.setMaximumHeight(200)
        self.drives_list.itemClicked.connect(self._on_drive_clicked)
        row.addWidget(self.drives_list, 1)
        side = QVBoxLayout()
        btn_refresh = QPushButton("↻  Volver a detectar")
        btn_refresh.setToolTip("Por ejemplo después de conectar un pendrive")
        btn_refresh.clicked.connect(self._refresh_drives)
        btn_browse = QPushButton("Otra carpeta…")
        btn_browse.clicked.connect(self._browse_dest)
        side.addWidget(btn_refresh)
        side.addWidget(btn_browse)
        side.addStretch(1)
        row.addLayout(side)
        lay.addLayout(row)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.addWidget(QLabel("Carpeta:"), 0, 0)
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Elegí una unidad de la lista o una carpeta")
        self.dest_edit.textChanged.connect(lambda _: self._update_dest_info())
        form.addWidget(self.dest_edit, 0, 1)
        form.addWidget(QLabel("Nombre:"), 1, 0)
        self.name_edit = QLineEdit(default_backup_name())
        self.name_edit.setToolTip("Si usás un nombre que ya existe en el destino, los archivos "
                                  "iguales se saltean (sirve para retomar un backup cortado)")
        form.addWidget(self.name_edit, 1, 1)
        opts = QHBoxLayout()
        opts.setSpacing(24)
        self.cb_group = QCheckBox("Separar por categoría (Imágenes/, Documentos/…)")
        self.cb_group.setChecked(True)
        self.cb_verify = QCheckBox("Verificar cada copia (más lento, más seguro)")
        opts.addWidget(self.cb_group)
        opts.addWidget(self.cb_verify)
        opts.addStretch(1)
        form.addLayout(opts, 2, 1)
        form.setColumnStretch(1, 1)
        lay.addLayout(form)

        lay.addSpacing(4)
        lay.addWidget(_label("Espacio", "sectionTitle"))
        self.space_bar = SpaceBar()
        lay.addWidget(self.space_bar)
        self.space_label = QLabel()
        self.space_label.setWordWrap(True)
        lay.addWidget(self.space_label)

        self.warn_box = QFrame()
        self.warn_box.setObjectName("warnBox")
        wl = QHBoxLayout(self.warn_box)
        wl.setContentsMargins(10, 8, 10, 8)
        self.warn_icon = QLabel()
        self.warn_icon.setFixedSize(28, 28)
        self.warn_text = QLabel()
        self.warn_text.setWordWrap(True)
        wl.addWidget(self.warn_icon, 0, Qt.AlignmentFlag.AlignTop)
        wl.addWidget(self.warn_text, 1)
        lay.addWidget(self.warn_box)
        lay.addStretch(1)
        return page

    def _refresh_drives(self) -> None:
        current = self.dest_edit.text().strip()
        self.drives_list.clear()
        drives = list_drives()
        drives.sort(key=lambda d: (not d.is_removable, d.root))   # pendrives primero
        sysdrive = system_drive().upper()
        color = themes.current().glow or themes.current().accent
        for d in drives:
            is_sys = d.root.upper() == sysdrive
            text = d.describe() + ("\nDisco del sistema: se borra al reinstalar" if is_sys else
                                   "\nExtraíble" if d.is_removable else "\nDisco")
            it = QListWidgetItem(icon("usb" if d.is_removable else "drive", color), text)
            it.setData(Qt.ItemDataRole.UserRole, d.root)
            it.setData(Qt.ItemDataRole.UserRole + 1, "usb" if d.is_removable else "drive")
            it.setSizeHint(QSize(0, 48))
            self.drives_list.addItem(it)
            if current and os.path.normcase(current) == os.path.normcase(d.root):
                it.setSelected(True)
        if not drives:
            it = QListWidgetItem("No se detectaron unidades: elegí una carpeta con «Otra carpeta…»")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.drives_list.addItem(it)
        self._update_dest_info()

    def _on_drive_clicked(self, item: QListWidgetItem) -> None:
        root = item.data(Qt.ItemDataRole.UserRole)
        if root:
            self.dest_edit.setText(root)

    def _browse_dest(self) -> None:
        start = self.dest_edit.text() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Carpeta de destino del backup", start)
        if folder:
            self.dest_edit.setText(os.path.normpath(folder))

    def _dest_warnings(self, dest: str) -> tuple[list[str], bool]:
        """(avisos, se_puede_continuar) para el destino elegido."""
        if not dest:
            return ["Elegí dónde guardar el backup."], False
        if not os.path.isdir(dest):
            return ["La carpeta de destino no existe."], False
        warnings: list[str] = []
        needed = required_space(self.model.checked_items())
        try:
            free = shutil.disk_usage(dest).free
        except OSError:
            return ["No se puede leer el destino."], False
        if needed > free:
            warnings.append(f"No alcanza el espacio: hay {format_size(free)} libres y se necesitan "
                            f"{format_size(needed)}. El backup va a quedar incompleto.")
        fs = filesystem_of(dest)
        if fs.upper() == "FAT32":
            big = [i for i in self.model.checked_items() if i.size >= 4 * 1024 ** 3]
            warnings.append("El destino es FAT32: no admite archivos de 4 GB o más"
                            + (f" (hay {len(big)} marcados)." if big else "."))
        if IS_WINDOWS and os.path.splitdrive(os.path.abspath(dest))[0].upper() + "\\" == system_drive().upper():
            warnings.append("El destino está en el disco del sistema, que se borra al reinstalar. "
                            "Usá un disco externo o un pendrive.")
        has_drivers = any(i.kind is ItemKind.DRIVER for i in self.model.checked_items())
        if IS_WINDOWS and not is_admin() and (has_drivers or (self.cb_wifi.isChecked()
                                                              and self.cb_wifi_keys.isChecked())):
            warnings.append("Sin permisos de administrador no se pueden exportar los drivers "
                            "ni las claves Wi-Fi.")
        dest_norm = os.path.normcase(os.path.abspath(dest))
        for r in self._scanned_roots:
            rn = os.path.normcase(os.path.abspath(r))
            if dest_norm == rn or dest_norm.startswith(rn.rstrip(os.sep) + os.sep):
                warnings.append("El destino está dentro de una carpeta que se recorrió "
                                "(las búsquedas siguientes lo saltean).")
                break
        return warnings, True

    def _update_dest_info(self) -> None:
        if not hasattr(self, "space_label"):
            return
        t = themes.current()
        dest = self.dest_edit.text().strip()
        needed = required_space(self.model.checked_items())
        need_color = (t.grad[0] if t.grad else t.accent)
        parts = [f"<span style='color:{t.muted}'>■</span> Ocupado",
                 f"<span style='color:{need_color}'>■</span> A copiar: <b>{format_size(needed)}</b>"]
        if dest and os.path.isdir(dest):
            try:
                usage = shutil.disk_usage(dest)
                fs = filesystem_of(dest)
                self.space_bar.set_values(usage.total, usage.free, needed)
                color = "" if usage.free >= needed else f" style='color:{t.danger}'"
                parts.append(f"<span{color}>Libre: <b>{format_size(usage.free)}</b></span> de "
                             f"{format_size(usage.total)}" + (f" · {fs}" if fs else ""))
            except OSError:
                self.space_bar.set_values(0, 0, 0)
        else:
            self.space_bar.set_values(0, 0, 0)
        self.space_label.setText("   ·   ".join(parts))
        warnings, _ok = self._dest_warnings(dest)
        self.warn_box.setVisible(bool(warnings))
        self.warn_icon.setPixmap(icon("warning", t.danger).pixmap(28, 28))
        self.warn_text.setText("<br>".join(f"• {html.escape(w)}" for w in warnings))
        # Resaltar en la lista la unidad elegida
        for i in range(self.drives_list.count()):
            it = self.drives_list.item(i)
            root = it.data(Qt.ItemDataRole.UserRole)
            it.setSelected(bool(root) and os.path.normcase(root) == os.path.normcase(dest))
        if self.pages.currentIndex() == P_DEST:
            self._update_nav()

    # ---------------------------------------------------------- 5. Copiando
    def _page_copy(self) -> QWidget:
        page, lay = self._page("Copiando…", "No desconectes el disco de destino hasta que termine.")
        lay.addStretch(1)
        self.copy_phase = _label("", "sectionTitle")
        lay.addWidget(self.copy_phase)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(30)
        self.progress.setFormat("0 %")
        lay.addWidget(self.progress)
        self.copy_status = _label("")
        lay.addWidget(self.copy_status)
        self.copy_current = _muted("")
        lay.addWidget(self.copy_current)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_log = QToolButton()
        self.btn_log.setText("Ver registro")
        self.btn_log.setCheckable(True)
        self.btn_cancel_backup = QPushButton("Cancelar backup")
        self.btn_cancel_backup.clicked.connect(self._cancel_backup)
        row.addWidget(self.btn_log)
        row.addWidget(self.btn_cancel_backup)
        lay.addLayout(row)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setVisible(False)
        self.btn_log.toggled.connect(self.log_view.setVisible)
        lay.addWidget(self.log_view, 2)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------- 6. Listo
    def _page_done(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 6, 4, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        self.done_icon = QLabel()
        self.done_icon.setFixedSize(56, 56)
        col = QVBoxLayout()
        self.done_title = _label("", "pageTitle")
        self.done_subtitle = _label("", "pageSubtitle")
        col.addWidget(self.done_title)
        col.addWidget(self.done_subtitle)
        head.addWidget(self.done_icon, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(col, 1)
        lay.addLayout(head)
        lay.addSpacing(6)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tile_copied = StatTile("check", "archivos copiados")
        self.tile_skipped = StatTile("folder", "ya estaban en el destino (salteados)")
        self.tile_bookmarks = StatTile("bookmarks", "perfiles de marcadores")
        self.tile_drivers = StatTile("drivers", "drivers exportados")
        self.tile_errors = StatTile("warning", "errores")
        self.tile_time = StatTile("clock", "duración")
        for i, tile in enumerate((self.tile_copied, self.tile_skipped, self.tile_bookmarks,
                                  self.tile_drivers, self.tile_errors, self.tile_time)):
            grid.addWidget(tile, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addSpacing(6)
        self.done_hint = _muted("")
        lay.addWidget(self.done_hint)
        row = QHBoxLayout()
        self.btn_open_backup = QPushButton("Abrir carpeta del backup")
        self.btn_open_backup.setObjectName("primary")
        self.btn_open_backup.clicked.connect(self._open_backup_folder)
        self.btn_open_errors = QPushButton("Ver errores")
        self.btn_open_errors.clicked.connect(self._open_errors)
        btn_new = QPushButton("Nuevo backup")
        btn_new.clicked.connect(self._new_backup)
        row.addWidget(self.btn_open_backup)
        row.addWidget(self.btn_open_errors)
        row.addStretch(1)
        row.addWidget(btn_new)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    # ============================================================ navegación
    def _busy(self) -> bool:
        return self._scan_worker is not None or self._backup_worker is not None

    def _go_to(self, page: int) -> None:
        self.pages.setCurrentIndex(page)
        self.header.set_current(page)
        if page == P_DEST:
            self._update_dest_info()
        self._update_nav()

    def _on_step_clicked(self, step: int) -> None:
        if step <= LAST_NAVIGABLE and not self._busy():
            self._go_to(step)

    def _mark_scan_dirty(self) -> None:
        """Cambió el origen o qué buscar: hay que volver a buscar antes de seguir."""
        if self._has_results:
            self._has_results = False
            self.header.max_reachable = min(self.header.max_reachable, P_WHAT)
            self.header.update()
        if hasattr(self, "btn_next"):
            self._update_nav()

    def _update_nav(self) -> None:
        page = self.pages.currentIndex()
        busy = self._busy()
        self.header.locked = busy
        self.btn_back.setVisible(page not in (P_ORIGIN, P_COPY, P_DONE))
        self.btn_back.setEnabled(not busy)
        self.btn_next.setVisible(page not in (P_COPY, P_DONE))
        hint = ""
        if page == P_ORIGIN:
            roots = self._checked_roots()
            self.btn_next.setText("Siguiente  ›")
            self.btn_next.setEnabled(True)
            hint = (f"{len(roots)} ubicación(es) para recorrer" if roots
                    else "Sin ubicaciones: sólo se van a buscar marcadores y drivers")
        elif page == P_WHAT:
            if self._has_results:
                self.btn_next.setText("Ver resultados  ›")
                hint = "No cambiaste nada desde la última búsqueda"
            else:
                self.btn_next.setText("Buscar archivos  ›")
            self.btn_next.setEnabled(True)
        elif page == P_REVIEW:
            self.btn_next.setText("Elegir destino  ›")
            something = self.model.totals()[2] > 0 or self.cb_wifi.isChecked() or self.cb_programs.isChecked()
            self.btn_next.setEnabled(not busy and something)
            if busy:
                hint = "Buscando… podés ir revisando mientras tanto"
            elif not something:
                hint = "No hay nada marcado para copiar"
        elif page == P_DEST:
            self.btn_next.setText("Iniciar backup  ›")
            _w, ok = self._dest_warnings(self.dest_edit.text().strip())
            self.btn_next.setEnabled(ok and not busy)
        self.nav_hint.setText(hint)

    def _go_next(self) -> None:
        page = self.pages.currentIndex()
        if page == P_ORIGIN:
            self._go_to(P_WHAT)
        elif page == P_WHAT:
            if self._has_results:
                self._go_to(P_REVIEW)
            else:
                self._start_scan()
        elif page == P_REVIEW:
            self._go_to(P_DEST)
        elif page == P_DEST:
            self._start_backup()

    def _go_back(self) -> None:
        page = self.pages.currentIndex()
        if page in (P_WHAT, P_REVIEW, P_DEST) and not self._busy():
            self._go_to(page - 1)

    def _new_backup(self) -> None:
        if self._busy():
            return
        self.name_edit.setText(default_backup_name())
        self._go_to(P_ORIGIN)

    # ================================================================ temas
    def set_theme(self, key: str) -> None:
        self._theme_key = key
        themes.apply_theme(key)
        self.settings.setValue("theme", key)
        if key in self.theme_actions:
            self.theme_actions[key].setChecked(True)
        color = themes.current().glow or themes.current().accent
        for lst in (self.roots_list, self.drives_list):
            for i in range(lst.count()):
                it = lst.item(i)
                kind = it.data(Qt.ItemDataRole.UserRole + 1)
                if kind:
                    it.setIcon(icon(kind, color))
        self._update_dest_info()
        if self._last_result is not None:
            self._fill_done_page(self._last_result, update_only=True)
        for w in self.findChildren(QWidget):
            if isinstance(w, (OptionCard, StatTile, StepHeader, SpaceBar)):
                w.update()

    def _about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"Acerca de {APP_NAME}")
        box.setIconPixmap(themes.app_icon().pixmap(64, 64))
        box.setText(f"<b>{APP_NAME} {APP_VERSION}</b><br>Backup de archivos personales, "
                    "marcadores, drivers y redes Wi-Fi antes de reinstalar Windows."
                    "<br><br>Python + PySide6")
        box.exec()

    # ================================================================ búsqueda
    def _start_scan(self) -> None:
        roots = self._checked_roots()
        enabled = {k for k, cb in self.cat_checks.items() if cb.isChecked()}
        if not roots and not self.cb_bookmarks.isChecked() and not self.cb_drivers.isChecked():
            QMessageBox.information(self, APP_NAME, "Marcá al menos una ubicación para recorrer, "
                                    "o los marcadores o drivers.")
            return
        missing = [r for r in roots if not os.path.isdir(r)]
        if missing:
            QMessageBox.warning(self, APP_NAME, "Estas carpetas no existen:\n" + "\n".join(missing))
            return
        if not enabled:
            roots = []   # sólo marcadores y/o drivers
        dest = self.dest_edit.text().strip()
        opts = ScanOptions(
            roots=roots,
            enabled_categories=enabled,
            min_kb={cats.IMAGES.key: self.spin_min_img.value()},
            excluded_dir_names=self._excluded_dirs(),
            excluded_paths=[dest] if dest and os.path.isdir(dest) and len(dest) > 3 else [],
            skip_cloud_only=self.cb_skip_cloud.isChecked(),
        )
        self._scanned_roots = roots
        self.model.clear()
        self.filter_edit.clear()
        self._apply_filter()
        self.preview_image.clear()
        self.preview_info.clear()
        self.scan_info.clear()
        self._scan_started = time.monotonic()
        self._save_settings()

        self._scan_worker = ScanWorker(opts, self.cb_bookmarks.isChecked(),
                                       self.cb_drivers.isChecked(), users_root())
        self._scan_worker.batch.connect(self._on_scan_batch)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.status.connect(self._on_scan_status)
        self._scan_worker.failed.connect(lambda tb: self._append_log("ERROR en la búsqueda:\n" + tb))
        self._scan_worker.finished.connect(self._on_scan_finished)
        self.scan_strip.setVisible(True)
        self.scan_text.setText("Preparando la búsqueda…")
        self.btn_cancel_scan.setEnabled(True)
        self._go_to(P_REVIEW)
        self._thread = start_in_thread(self._scan_worker, self)
        self._update_nav()

    def _cancel_scan(self) -> None:
        if self._scan_worker:
            self._scan_worker.cancel()
            self.btn_cancel_scan.setEnabled(False)
            self.scan_text.setText("Deteniendo…")

    def _on_scan_status(self, text: str) -> None:
        self.scan_text.setText(text)
        self.status_label.setText(text)

    def _on_scan_batch(self, items: list[FoundItem]) -> None:
        first = self.model.rowCount() == 0
        self.model.add_items(items)
        if first and self.model.rowCount():
            self.tree.expandToDepth(0)

    def _on_scan_progress(self, stats: ScanStats, current: str) -> None:
        elapsed = time.monotonic() - self._scan_started
        text = (f"Recorriendo… {format_count(stats.dirs_scanned)} carpetas · "
                f"{format_count(stats.files_seen)} archivos revisados · "
                f"{format_count(stats.items_found)} encontrados · {int(elapsed)} s")
        self.scan_text.setText(f"{text}<br><span style='font-size:small'>"
                               f"{_esc(_shorten(current, 110))}</span>")
        self.status_label.setText(text)

    def _on_scan_finished(self, stats: ScanStats) -> None:
        self._last_worker = self._scan_worker   # se mantiene vivo hasta que el hilo termine
        self._scan_worker = None
        if self._closing:
            return
        self.scan_strip.setVisible(False)
        self.model.sort(self.tree.header().sortIndicatorSection(), self.tree.header().sortIndicatorOrder())
        self.tree.expandToDepth(0)
        count, size, _, _ = self.model.totals()
        state = "Búsqueda detenida" if stats.cancelled else "Búsqueda terminada"
        self.status_label.setText(
            f"{state}: {format_count(count)} elementos ({format_size(size)}) en "
            f"{stats.seconds:.0f} s · {format_count(stats.dirs_scanned)} carpetas.")
        extra = []
        if stats.cancelled:
            extra.append("La búsqueda se detuvo antes de terminar: puede faltar algo")
        if stats.errors:
            extra.append(f"{format_count(stats.errors)} carpetas sin acceso")
        if stats.skipped_cloud:
            extra.append(f"{format_count(stats.skipped_cloud)} archivos sólo en la nube omitidos")
        if stats.skipped_backups:
            extra.append(f"{format_count(stats.skipped_backups)} backups anteriores salteados")
        self.scan_info.setText(" · ".join(extra))
        self._has_results = not stats.cancelled
        self._update_summary()
        self._update_nav()

    def _on_totals_changed(self, _count: int, _size: int) -> None:
        self._update_summary()
        if not self._scan_worker:   # durante la búsqueda se actualiza al final
            if self.pages.currentIndex() == P_DEST:
                self._update_dest_info()
            self._update_nav()

    def _update_summary(self) -> None:
        total, total_size, checked, checked_size = self.model.totals()
        if not total:
            self.summary_label.setText("No se encontró nada todavía.")
            return
        cats_txt = " · ".join(f"{label}: {format_count(n)}" for label, n, _ in self.model.category_summary())
        self.summary_label.setText(
            f"Marcados para el backup: <b>{format_count(checked)}</b> de {format_count(total)} "
            f"({format_size(checked_size)} de {format_size(total_size)})<br>{cats_txt}")

    # ================================================================ backup
    def _start_backup(self) -> None:
        items = self.model.checked_items()
        wifi = self.cb_wifi.isChecked()
        programs = self.cb_programs.isChecked()
        if not items and not wifi and not programs:
            QMessageBox.information(self, APP_NAME, "No hay nada marcado para copiar. "
                                    "Primero buscá archivos.")
            return
        dest = self.dest_edit.text().strip()
        warnings, ok = self._dest_warnings(dest)
        if not ok:
            QMessageBox.warning(self, APP_NAME, warnings[0])
            return
        if warnings:
            msg = "\n\n".join("• " + w for w in warnings) + "\n\n¿Continuar de todos modos?"
            if QMessageBox.question(self, APP_NAME, msg) != QMessageBox.StandardButton.Yes:
                return
        name = self.name_edit.text().strip() or default_backup_name()
        options = CopyOptions(
            dest_root=dest, backup_name=name,
            group_by_category=self.cb_group.isChecked(),
            verify=self.cb_verify.isChecked(),
            wifi_profiles=wifi,
            wifi_include_keys=wifi and self.cb_wifi_keys.isChecked(),
            programs_list=programs,
        )
        self._save_settings()
        self.log_view.clear()
        self.btn_log.setText("Ver registro")
        self.progress.setValue(0)
        self.progress.setFormat("0 %")
        self.copy_phase.setText("Preparando…")
        self.copy_status.setText("")
        self.copy_current.setText("")
        self.btn_cancel_backup.setEnabled(True)
        self._copy_started = time.monotonic()
        self._backup_worker = BackupWorker(items, options)
        self._backup_worker.progress.connect(self._on_copy_progress)
        self._backup_worker.log.connect(self._append_log)
        self._backup_worker.finished.connect(self._on_backup_finished)
        self._go_to(P_COPY)
        self._thread = start_in_thread(self._backup_worker, self)
        self._update_nav()

    def _cancel_backup(self) -> None:
        if self._backup_worker:
            self._backup_worker.cancel()
            self.btn_cancel_backup.setEnabled(False)
            self.copy_phase.setText("Cancelando… (se termina el archivo actual y se guarda el informe)")

    def _on_copy_progress(self, p: CopyProgress) -> None:
        if p.bytes_total:
            frac = p.bytes_done / p.bytes_total
        else:
            frac = p.files_done / p.files_total if p.files_total else 0
        frac = max(0.0, min(frac, 1.0))
        self.progress.setValue(int(frac * 1000))
        self.progress.setFormat(f"{frac * 100:.1f} %".replace(".", ","))
        elapsed = time.monotonic() - self._copy_started
        eta = ""
        if p.bytes_done and elapsed > 3 and p.bytes_total > p.bytes_done:
            rate = p.bytes_done / elapsed
            eta = f" · {format_size(rate)}/s · faltan ~{_fmt_duration((p.bytes_total - p.bytes_done) / rate)}"
        if self._backup_worker is not None and self._backup_worker.cancel_event.is_set():
            pass   # se deja el texto de "Cancelando…"
        else:
            self.copy_phase.setText(p.phase)
        self.copy_status.setText(
            f"{format_count(p.files_done)} de {format_count(p.files_total)} elementos · "
            f"{format_size(p.bytes_done)} de {format_size(p.bytes_total)}{eta}")
        self.status_label.setText(f"{p.phase} · {frac * 100:.0f} %")
        self.copy_current.setText(_esc(_shorten(p.current, 140)))

    def _on_backup_finished(self, r: CopyResult) -> None:
        self._last_worker = self._backup_worker
        self._backup_worker = None
        if self._closing:
            return
        self._last_result = r
        self._fill_done_page(r)
        self._go_to(P_DONE)
        self.name_edit.setText(default_backup_name())

    def _fill_done_page(self, r: CopyResult, update_only: bool = False) -> None:
        t = themes.current()
        if not update_only:
            elapsed = time.monotonic() - self._copy_started
            self._last_elapsed = elapsed
            if not r.cancelled:
                self.progress.setValue(1000)
                self.progress.setFormat("100 %")
        elapsed = getattr(self, "_last_elapsed", 0.0)
        if r.cancelled:
            title, subtitle, ico, col = ("Backup cancelado", "Quedó incompleto. Podés retomarlo "
                                         "usando el mismo nombre y destino.", "warning", t.danger)
        elif r.failed:
            title, subtitle, ico, col = ("Backup terminado con errores", "Revisá errores.log: "
                                         "puede haber archivos abiertos o sin permiso.", "warning", t.danger)
        else:
            title, subtitle, ico, col = ("Backup terminado", "Ya podés reinstalar. Antes, abrí la "
                                         "carpeta y comprobá que estén tus archivos.", "check",
                                         t.glow or t.accent)
        self.done_title.setText(title)
        self.done_subtitle.setText(subtitle)
        self.done_icon.setPixmap(icon(ico, col).pixmap(56, 56))
        self.copy_status.setText(f"{title} · {_fmt_duration(elapsed)}")
        self.status_label.setText(f"{title} · {_fmt_duration(elapsed)}")
        self.tile_copied.set_value(format_count(r.copied))
        self.tile_copied.caption = f"archivos copiados ({format_size(r.bytes_copied)})"
        self.tile_skipped.set_value(format_count(r.skipped_existing))
        self.tile_bookmarks.set_value(str(r.bookmarks_saved))
        self.tile_drivers.set_value(str(r.drivers_exported))
        self.tile_errors.set_value(format_count(r.failed), alert=r.failed > 0)
        self.tile_time.set_value(_fmt_duration(elapsed))
        self.done_hint.setText(f"Carpeta: {r.backup_dir}<br>El detalle de cada elemento está en "
                               "manifiesto.csv dentro de esa carpeta.")
        self.btn_open_errors.setVisible(bool(r.failed))
        self.btn_open_backup.setEnabled(bool(r.backup_dir) and os.path.isdir(r.backup_dir))

    def _open_backup_folder(self) -> None:
        r = self._last_result
        if r and r.backup_dir and os.path.isdir(r.backup_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(r.backup_dir))

    def _open_errors(self) -> None:
        r = self._last_result
        if r:
            path = os.path.join(r.backup_dir, "errores.log")
            if os.path.isfile(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ================================================================ varios
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {text}")
        if text.startswith("ERROR") and not self.btn_log.isChecked():
            self.btn_log.setText("Ver registro (hay errores)")

    def _restart_as_admin(self) -> None:
        self._save_settings()
        if relaunch_as_admin():
            self.close()
        else:
            QMessageBox.warning(self, APP_NAME, "No se pudo reiniciar como administrador.")

    def _load_settings(self) -> None:
        s = self.settings
        dest = s.value("dest", "")
        if dest and os.path.isdir(dest):
            self.dest_edit.setText(dest)
        for key, cb in self.cat_checks.items():
            cb.setChecked(s.value(f"cat/{key}", True, type=bool))
        self.cb_bookmarks.setChecked(s.value("bookmarks", True, type=bool))
        self.cb_drivers.setChecked(s.value("drivers", IS_WINDOWS, type=bool))
        self.cb_wifi.setChecked(s.value("wifi", IS_WINDOWS, type=bool))
        self.cb_wifi_keys.setChecked(s.value("wifi_keys", False, type=bool))
        self.cb_wifi_keys.setEnabled(self.cb_wifi.isChecked())
        self.cb_programs.setChecked(s.value("programs", IS_WINDOWS, type=bool))
        self.cb_skip_cloud.setChecked(s.value("skip_cloud", True, type=bool))
        self.cb_group.setChecked(s.value("group", True, type=bool))
        self.cb_verify.setChecked(s.value("verify", False, type=bool))
        self.spin_min_img.setValue(s.value("min_img_kb", cats.IMAGES.default_min_kb, type=int))
        extra_roots = s.value("extra_roots", [])
        if isinstance(extra_roots, str):
            extra_roots = [extra_roots]
        self.roots_list.blockSignals(True)
        for r in extra_roots or []:
            if os.path.isdir(r):
                self._add_root_item(r, "Carpeta agregada", checked=False)
        self.roots_list.blockSignals(False)
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("dest", self.dest_edit.text().strip())
        for key, cb in self.cat_checks.items():
            s.setValue(f"cat/{key}", cb.isChecked())
        s.setValue("bookmarks", self.cb_bookmarks.isChecked())
        s.setValue("drivers", self.cb_drivers.isChecked())
        s.setValue("wifi", self.cb_wifi.isChecked())
        s.setValue("wifi_keys", self.cb_wifi_keys.isChecked())
        s.setValue("programs", self.cb_programs.isChecked())
        s.setValue("skip_cloud", self.cb_skip_cloud.isChecked())
        s.setValue("group", self.cb_group.isChecked())
        s.setValue("verify", self.cb_verify.isChecked())
        s.setValue("min_img_kb", self.spin_min_img.value())
        default_roots = {os.path.normcase(users_root())} | {os.path.normcase(d.root) for d in list_drives()}
        extra = [self.roots_list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.roots_list.count())]
        s.setValue("extra_roots", [r for r in extra if os.path.normcase(r) not in default_roots])
        s.setValue("geometry", self.saveGeometry())

    def _wait_thread(self, ms: int) -> bool:
        """Espera al hilo de trabajo. True si ya no está corriendo."""
        if self._thread is None:
            return True
        try:
            # quit() se encola: si el worker sigue en run(), el hilo sale apenas termine
            self._thread.quit()
            return self._thread.wait(ms)
        except RuntimeError:
            return True   # el hilo ya terminó y Qt lo liberó

    def closeEvent(self, event) -> None:
        worker = self._backup_worker or self._scan_worker
        if worker is not None and not self._closing:
            msg = ("Hay un backup en curso. Si cerrás ahora va a quedar incompleto. ¿Cerrar igual?"
                   if self._backup_worker else "Hay una búsqueda en curso. ¿Cerrar igual?")
            if QMessageBox.question(self, APP_NAME, msg) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._closing = True
            worker.cancel()
            # El hilo termina al procesar la cancelación, pero si está esperando a
            # pnputil o netsh puede tardar minutos. Destruir un QThread en marcha
            # hace caer la app, así que se oculta la ventana y se cierra al terminar.
            if not self._wait_thread(3_000):
                self._save_settings()
                self.hide()
                worker.finished.connect(lambda *_: QTimer.singleShot(0, self.close))
                event.ignore()
                return
        elif worker is not None:
            event.ignore()   # ya se está esperando al hilo
            return
        self._wait_thread(5_000)
        self._save_settings()
        event.accept()


def _esc(text: str) -> str:
    return html.escape(text or "")


def _shorten(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return "…" + text[-(n - 1):]


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"
