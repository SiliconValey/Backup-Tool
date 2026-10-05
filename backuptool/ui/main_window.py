"""Ventana principal de BackupTool."""

from __future__ import annotations

import os
import shutil
import time

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QImageReader, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QSplitter, QToolButton,
                               QTreeView, QVBoxLayout, QWidget)

from .. import APP_NAME, APP_VERSION
from ..core import categories as cats
from ..core.copier import CopyOptions, CopyProgress, default_backup_name, required_space
from ..core.models import CopyResult, FoundItem, ItemKind, ScanStats
from ..core.scanner import ScanOptions
from ..core.winutils import (IS_WINDOWS, format_count, format_size, filesystem_of, is_admin,
                             list_drives, open_in_explorer, relaunch_as_admin, system_drive,
                             users_root)
from .file_model import (COL_DATE, COL_NAME, COL_SIZE, COL_COUNT, ITEM_ROLE,
                         FoundItemsModel, FoundItemsProxy)
from . import themes
from .workers import BackupWorker, ScanWorker, start_in_thread

def _muted(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(True)
    return lbl


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — Backup de Windows")
        self.resize(1380, 860)
        self.settings = QSettings(APP_NAME, APP_NAME)

        self._scan_worker: ScanWorker | None = None
        self._backup_worker: BackupWorker | None = None
        self._thread = None
        self._scanned_roots: list[str] = []
        self._copy_started = 0.0

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
        self._update_space_label()

    # ================================================================ UI
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 8)

        if IS_WINDOWS and not is_admin():
            outer.addWidget(self._build_admin_banner())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_source_panel())
        splitter.addWidget(self._build_explorer())
        splitter.addWidget(self._build_preview())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([330, 820, 260])
        outer.addWidget(splitter, 1)
        outer.addWidget(self._build_destination())
        self.setCentralWidget(central)

        self.status_label = QLabel("Listo. Elegí dónde buscar y presioná «Buscar archivos».")
        self.statusBar().addWidget(self.status_label, 1)

    def _build_menu(self) -> None:
        bar = self.menuBar()
        m_file = bar.addMenu("&Archivo")
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

        m_help = bar.addMenu("A&yuda")
        act_about = QAction("&Acerca de BackupTool", self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

    def set_theme(self, key: str) -> None:
        self._theme_key = key
        themes.apply_theme(key)
        self.settings.setValue("theme", key)
        if key in self.theme_actions:
            self.theme_actions[key].setChecked(True)
        self._update_space_label()   # usa el color de aviso del tema

    def _about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"Acerca de {APP_NAME}")
        box.setIconPixmap(themes.app_icon().pixmap(64, 64))
        box.setText(f"<b>{APP_NAME} {APP_VERSION}</b><br>Backup de archivos personales, "
                    "marcadores y drivers de Windows.<br><br>Python + PySide6")
        box.exec()

    def _build_admin_banner(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("adminBanner")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 6, 10, 6)
        lbl = QLabel("⚠  La app no se está ejecutando como administrador: el backup de "
                     "<b>drivers</b> y de las <b>claves Wi-Fi</b> no va a funcionar.")
        lbl.setWordWrap(True)
        btn = QPushButton("Reiniciar como administrador")
        btn.clicked.connect(self._restart_as_admin)
        lay.addWidget(lbl, 1)
        lay.addWidget(btn)
        return frame

    # ---------------------------------------------------------- panel izquierdo
    def _build_source_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 6, 0)

        # 1. Dónde buscar
        g_roots = QGroupBox("1. Dónde buscar")
        rl = QVBoxLayout(g_roots)
        self.roots_list = QListWidget()
        self.roots_list.setMaximumHeight(96)
        rl.addWidget(self.roots_list)
        row = QHBoxLayout()
        btn_add = QPushButton("Agregar carpeta…")
        btn_add.clicked.connect(self._add_root_folder)
        btn_del = QPushButton("Quitar")
        btn_del.clicked.connect(self._remove_root)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        rl.addLayout(row)
        rl.addWidget(_muted("Para recorrer un disco entero agregá su raíz (por ejemplo C:\\). "
                            "Windows, Archivos de programa y AppData se excluyen siempre."))
        self._populate_roots()
        lay.addWidget(g_roots)

        # 2. Qué buscar
        g_what = QGroupBox("2. Qué buscar")
        wl = QGridLayout(g_what)
        self.cat_checks: dict[str, QCheckBox] = {}
        for n, cat in enumerate(cats.ALL_CATEGORIES):
            cb = QCheckBox(cat.label)
            cb.setChecked(True)
            cb.setToolTip(cat.description)
            self.cat_checks[cat.key] = cb
            wl.addWidget(cb, n // 2, n % 2)
        next_row = (len(cats.ALL_CATEGORIES) + 1) // 2
        self.cb_bookmarks = QCheckBox("Marcadores de navegadores")
        self.cb_bookmarks.setChecked(True)
        self.cb_bookmarks.setToolTip("Chrome, Edge, Brave, Vivaldi, Opera y Firefox de todos los usuarios")
        self.cb_drivers = QCheckBox("Drivers de terceros")
        self.cb_drivers.setChecked(IS_WINDOWS)
        self.cb_drivers.setToolTip("Se exportan con pnputil (requiere administrador)")
        wl.addWidget(self.cb_bookmarks, next_row, 0, 1, 2)
        wl.addWidget(self.cb_drivers, next_row + 1, 0, 1, 2)
        lay.addWidget(g_what)

        # Opciones
        g_opt = QGroupBox("Opciones de búsqueda")
        ol = QGridLayout(g_opt)
        ol.addWidget(QLabel("Ignorar imágenes menores a"), 0, 0)
        self.spin_min_img = QSpinBox()
        self.spin_min_img.setRange(0, 10_000)
        self.spin_min_img.setSuffix(" KB")
        self.spin_min_img.setValue(cats.IMAGES.default_min_kb)
        ol.addWidget(self.spin_min_img, 0, 1)
        self.cb_skip_cloud = QCheckBox("Omitir archivos que sólo están en la nube")
        self.cb_skip_cloud.setChecked(True)
        self.cb_skip_cloud.setToolTip("Archivos de OneDrive no descargados: leerlos obligaría a bajarlos")
        ol.addWidget(self.cb_skip_cloud, 1, 0, 1, 2)
        btn_excl = QPushButton("Carpetas excluidas…")
        btn_excl.clicked.connect(self._edit_exclusions)
        ol.addWidget(btn_excl, 2, 0, 1, 2)
        lay.addWidget(g_opt)

        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(300)

        # Botones fuera del scroll: siempre visibles
        column = QWidget()
        cl = QVBoxLayout(column)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(scroll, 1)
        row = QHBoxLayout()
        self.btn_scan = QPushButton("Buscar archivos")
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self._start_scan)
        self.btn_cancel_scan = QPushButton("Detener")
        self.btn_cancel_scan.setEnabled(False)
        self.btn_cancel_scan.clicked.connect(self._cancel_scan)
        row.addWidget(self.btn_scan, 1)
        row.addWidget(self.btn_cancel_scan)
        cl.addLayout(row)
        self.scan_info = _muted("")
        cl.addWidget(self.scan_info)
        return column

    def _populate_roots(self) -> None:
        self.roots_list.clear()
        self._add_root_item(users_root(), "Perfiles de usuario", checked=True)
        sysdrive = system_drive().upper()
        for d in list_drives():
            if d.root.upper() == sysdrive:
                continue
            self._add_root_item(d.root, d.describe(), checked=False)

    def _add_root_item(self, path: str, label: str = "", checked: bool = True) -> None:
        for i in range(self.roots_list.count()):
            if os.path.normcase(self.roots_list.item(i).data(Qt.ItemDataRole.UserRole)) == os.path.normcase(path):
                self.roots_list.item(i).setCheckState(Qt.CheckState.Checked)
                return
        text = f"{path}  —  {label}" if label else path
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        item.setToolTip(path)
        self.roots_list.addItem(item)

    def _add_root_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Agregar carpeta o unidad a recorrer")
        if folder:
            self._add_root_item(os.path.normpath(folder))

    def _remove_root(self) -> None:
        for item in self.roots_list.selectedItems():
            self.roots_list.takeItem(self.roots_list.row(item))

    def _checked_roots(self) -> list[str]:
        roots = []
        for i in range(self.roots_list.count()):
            it = self.roots_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                roots.append(it.data(Qt.ItemDataRole.UserRole))
        return roots

    def _edit_exclusions(self) -> None:
        current = "\n".join(sorted(self._excluded_dirs()))
        text, ok = QInputDialog.getMultiLineText(
            self, "Carpetas excluidas",
            "Nombres de carpeta que no se recorren (uno por línea, en cualquier nivel):", current)
        if ok:
            names = sorted({t.strip() for t in text.splitlines() if t.strip()})
            self.settings.setValue("excluded_dirs", names)

    def _excluded_dirs(self) -> set[str]:
        saved = self.settings.value("excluded_dirs")
        if isinstance(saved, str):
            saved = [saved]
        return set(saved) if saved else set(cats.DEFAULT_EXCLUDED_DIRS)

    # ---------------------------------------------------------------- explorador
    def _build_explorer(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 0, 6, 0)
        self.tree = QTreeView()

        top = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filtrar por nombre o carpeta…")
        self.filter_edit.setClearButtonEnabled(True)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.filter_edit.textChanged.connect(lambda _: self._filter_timer.start())
        self.filter_edit.setMinimumWidth(160)
        top.addWidget(self.filter_edit, 1)
        for text, slot in (("Marcar todo", lambda: self.model.set_all_checked(True)),
                           ("Desmarcar todo", lambda: self.model.set_all_checked(False))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            top.addWidget(b)
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
        header.resizeSection(COL_NAME, 340)
        header.resizeSection(COL_COUNT, 80)
        header.resizeSection(COL_SIZE, 90)
        header.resizeSection(COL_DATE, 130)
        lay.addWidget(self.tree, 1)

        self.summary_label = _muted("Todavía no se buscó nada.")
        lay.addWidget(self.summary_label)
        return w

    def _set_view_model(self, model) -> None:
        """Sin filtro el árbol usa el modelo directo (mucho más rápido con grupos
        grandes expandidos); el proxy de filtrado sólo se usa mientras hay texto."""
        if self.tree.model() is model:
            return
        self.tree.setModel(model)
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
        else:
            self.proxy.set_filter_text("")
            self._set_view_model(self.model)
            self.tree.expandToDepth(0)

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
            act_check.triggered.connect(lambda: [self.model.set_checked(i, True) for i in sel])
            act_uncheck = QAction(f"Desmarcar seleccionados ({len(sel)})", self)
            act_uncheck.triggered.connect(lambda: [self.model.set_checked(i, False) for i in sel])
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

    # ---------------------------------------------------------------- vista previa
    def _build_preview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 0, 0, 0)
        lay.addWidget(QLabel("<b>Vista previa</b>"))
        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setMinimumSize(QSize(220, 220))
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

    def _on_current_changed(self, current, _previous) -> None:
        item: FoundItem | None = current.data(ITEM_ROLE) if current.isValid() else None
        self.preview_image.clear()
        if item is None:
            self.preview_info.setText(f"<b>{current.data() or ''}</b><br>"
                                      f"{current.data(Qt.ItemDataRole.ToolTipRole) or ''}"
                                      if current.isValid() else "")
            return
        lines = [f"<b>{_esc(item.name)}</b>"]
        if item.kind is ItemKind.FILE:
            lines.append(f"{item.category} · {item.group}")
            lines.append(f"Tamaño: {format_size(item.size)}")
            if item.mtime:
                lines.append("Modificado: " + time.strftime("%d/%m/%Y %H:%M", time.localtime(item.mtime)))
        elif item.kind is ItemKind.BOOKMARK:
            lines.append(f"Navegador: {item.extra.get('browser')}")
            lines.append(f"Usuario: {item.extra.get('user')} · perfil {item.extra.get('profile')}")
            if item.extra.get("count") is not None:
                lines.append(f"Marcadores: {item.extra['count']}")
            lines.append("Se copia el archivo original y se exporta a HTML.")
        elif item.kind is ItemKind.DRIVER:
            lines.append(f"Clase: {item.extra.get('class')}")
            lines.append(f"Fabricante: {item.extra.get('provider')}")
            if item.extra.get("version"):
                lines.append(f"Versión: {item.extra['version']}")
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

    # ---------------------------------------------------------------- destino
    def _build_destination(self) -> QWidget:
        g = QGroupBox("3. Destino del backup")
        grid = QGridLayout(g)

        grid.addWidget(QLabel("Unidad:"), 0, 0)
        self.drive_combo = QComboBox()
        self.drive_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.drive_combo.activated.connect(self._on_drive_chosen)
        btn_refresh = QToolButton()
        btn_refresh.setText("↻")
        btn_refresh.setToolTip("Volver a detectar unidades (por ejemplo después de conectar un pendrive)")
        btn_refresh.clicked.connect(self._refresh_drives)
        drow = QHBoxLayout()
        drow.addWidget(self.drive_combo, 1)
        drow.addWidget(btn_refresh)
        grid.addLayout(drow, 0, 1)

        grid.addWidget(QLabel("Carpeta:"), 1, 0)
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Elegí un disco externo o pendrive")
        self.dest_edit.textChanged.connect(lambda _: self._update_space_label())
        btn_browse = QPushButton("Elegir…")
        btn_browse.clicked.connect(self._browse_dest)
        prow = QHBoxLayout()
        prow.addWidget(self.dest_edit, 1)
        prow.addWidget(btn_browse)
        grid.addLayout(prow, 1, 1)

        grid.addWidget(QLabel("Nombre:"), 2, 0)
        self.name_edit = QLineEdit(default_backup_name())
        self.name_edit.setToolTip("Si usás un nombre que ya existe en el destino, los archivos "
                                  "iguales se saltean (sirve para retomar un backup)")
        grid.addWidget(self.name_edit, 2, 1)

        opts = QHBoxLayout()
        self.cb_group = QCheckBox("Separar por categoría")
        self.cb_group.setChecked(True)
        self.cb_group.setToolTip("Imágenes/, Audio/, Documentos/… manteniendo la ruta original adentro")
        self.cb_verify = QCheckBox("Verificar copia (más lento)")
        self.cb_wifi = QCheckBox("Perfiles Wi-Fi")
        self.cb_wifi.setChecked(IS_WINDOWS)
        self.cb_wifi_keys = QCheckBox("con contraseñas")
        self.cb_wifi_keys.setToolTip("Quedan en texto plano dentro del backup. Requiere administrador.")
        self.cb_wifi.toggled.connect(self.cb_wifi_keys.setEnabled)
        self.cb_programs = QCheckBox("Lista de programas instalados")
        self.cb_programs.setChecked(IS_WINDOWS)
        for cb in (self.cb_group, self.cb_verify, self.cb_wifi, self.cb_wifi_keys, self.cb_programs):
            opts.addWidget(cb)
        opts.addStretch(1)
        grid.addLayout(opts, 3, 0, 1, 2)

        self.space_label = QLabel()
        grid.addWidget(self.space_label, 4, 0, 1, 2)

        prow2 = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("")
        self.btn_backup = QPushButton("Iniciar backup")
        self.btn_backup.setObjectName("primary")
        self.btn_backup.clicked.connect(self._start_backup)
        self.btn_cancel_backup = QPushButton("Cancelar")
        self.btn_cancel_backup.setEnabled(False)
        self.btn_cancel_backup.clicked.connect(self._cancel_backup)
        self.btn_log = QToolButton()
        self.btn_log.setText("Registro")
        self.btn_log.setCheckable(True)
        prow2.addWidget(self.progress, 1)
        prow2.addWidget(self.btn_backup)
        prow2.addWidget(self.btn_cancel_backup)
        prow2.addWidget(self.btn_log)
        grid.addLayout(prow2, 5, 0, 1, 2)

        self.copy_status = _muted("")
        grid.addWidget(self.copy_status, 6, 0, 1, 2)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        self.log_view.setVisible(False)
        self.btn_log.toggled.connect(self.log_view.setVisible)
        grid.addWidget(self.log_view, 7, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        return g

    def _refresh_drives(self) -> None:
        current = self.dest_edit.text()
        self.drive_combo.clear()
        self.drive_combo.addItem("— Elegir unidad —", "")
        drives = list_drives()
        # Primero los extraíbles (pendrives), después los demás discos
        drives.sort(key=lambda d: (not d.is_removable, d.root))
        sysdrive = system_drive().upper()
        for d in drives:
            text = d.describe() + ("  (disco del sistema)" if d.root.upper() == sysdrive else "")
            self.drive_combo.addItem(text, d.root)
        if current:
            drive = os.path.splitdrive(current)[0].upper() + "\\"
            i = self.drive_combo.findData(drive)
            if i >= 0:
                self.drive_combo.setCurrentIndex(i)
        self._update_space_label()

    def _on_drive_chosen(self, index: int) -> None:
        root = self.drive_combo.itemData(index)
        if root:
            self.dest_edit.setText(root)

    def _browse_dest(self) -> None:
        start = self.dest_edit.text() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Carpeta de destino del backup", start)
        if folder:
            self.dest_edit.setText(os.path.normpath(folder))

    def _update_space_label(self) -> None:
        dest = self.dest_edit.text().strip() if hasattr(self, "dest_edit") else ""
        needed = self.model.totals()[3]
        danger = themes.current().danger
        parts = [f"Seleccionado: <b>{format_size(needed)}</b>"]
        if dest and os.path.isdir(dest):
            try:
                free = shutil.disk_usage(dest).free
                fs = filesystem_of(dest)
                ok = free >= needed
                color = "" if ok else f" style='color:{danger}'"
                parts.append(f"<span{color}>Libre en destino: <b>{format_size(free)}</b></span>"
                             + (f" ({fs})" if fs else ""))
                if not ok:
                    parts.append(f"<span style='color:{danger}'>No alcanza el espacio</span>")
                if fs.upper() == "FAT32":
                    parts.append("FAT32: no admite archivos de 4 GB o más")
            except OSError:
                parts.append("No se puede leer el destino")
        elif dest:
            parts.append(f"<span style='color:{danger}'>La carpeta no existe</span>")
        self.space_label.setText("   ·   ".join(parts))

    # ================================================================ búsqueda
    def _start_scan(self) -> None:
        roots = self._checked_roots()
        enabled = {k for k, cb in self.cat_checks.items() if cb.isChecked()}
        if not roots and not self.cb_bookmarks.isChecked() and not self.cb_drivers.isChecked():
            QMessageBox.information(self, APP_NAME, "Marcá al menos una carpeta o unidad para recorrer.")
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
        self.preview_image.clear()
        self.preview_info.clear()
        self._scan_started = time.monotonic()

        self._scan_worker = ScanWorker(opts, self.cb_bookmarks.isChecked(),
                                       self.cb_drivers.isChecked(), users_root())
        self._scan_worker.batch.connect(self._on_scan_batch)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.status.connect(self.status_label.setText)
        self._scan_worker.failed.connect(lambda tb: self._append_log("Error en la búsqueda:\n" + tb))
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._set_busy(True, scanning=True)
        self._thread = start_in_thread(self._scan_worker, self)

    def _cancel_scan(self) -> None:
        if self._scan_worker:
            self._scan_worker.cancel()
            self.status_label.setText("Deteniendo…")

    def _on_scan_batch(self, items: list[FoundItem]) -> None:
        first = self.model.rowCount() == 0
        self.model.add_items(items)
        if first and self.model.rowCount():
            self.tree.expandToDepth(0)

    def _on_scan_progress(self, stats: ScanStats, current: str) -> None:
        elapsed = time.monotonic() - self._scan_started
        self.status_label.setText(
            f"Recorriendo… {format_count(stats.dirs_scanned)} carpetas, "
            f"{format_count(stats.files_seen)} archivos revisados, "
            f"{format_count(stats.items_found)} encontrados · {int(elapsed)} s   {_shorten(current, 90)}")

    def _on_scan_finished(self, stats: ScanStats) -> None:
        self._last_worker = self._scan_worker   # se mantiene vivo hasta que el hilo termine
        self._scan_worker = None
        self._set_busy(False)
        self.model.sort(self.tree.header().sortIndicatorSection(), self.tree.header().sortIndicatorOrder())
        self.tree.expandToDepth(0)
        count, size, _, _ = self.model.totals()
        state = "Búsqueda detenida" if stats.cancelled else "Búsqueda terminada"
        self.status_label.setText(
            f"{state}: {format_count(count)} elementos ({format_size(size)}) en "
            f"{stats.seconds:.0f} s · {format_count(stats.dirs_scanned)} carpetas.")
        extra = []
        if stats.errors:
            extra.append(f"{format_count(stats.errors)} carpetas sin acceso")
        if stats.skipped_cloud:
            extra.append(f"{format_count(stats.skipped_cloud)} archivos sólo en la nube omitidos")
        self.scan_info.setText(" · ".join(extra))
        self._update_summary()
        self._update_space_label()

    def _on_totals_changed(self, count: int, size: int) -> None:
        self._update_summary()
        if not self._scan_worker:   # durante la búsqueda se actualiza al final
            self._update_space_label()

    def _update_summary(self) -> None:
        total, total_size, checked, checked_size = self.model.totals()
        if not total:
            self.summary_label.setText("No hay elementos.")
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
        if not dest or not os.path.isdir(dest):
            QMessageBox.warning(self, APP_NAME, "Elegí una carpeta de destino que exista "
                                "(por ejemplo un disco externo o un pendrive).")
            return
        name = self.name_edit.text().strip() or default_backup_name()

        warnings = []
        needed = required_space(items)
        free = shutil.disk_usage(dest).free
        if needed > free:
            warnings.append(f"El destino tiene {format_size(free)} libres y se necesitan "
                            f"{format_size(needed)}. El backup va a quedar incompleto.")
        if IS_WINDOWS and os.path.splitdrive(os.path.abspath(dest))[0].upper() + "\\" == system_drive().upper():
            warnings.append("El destino está en el mismo disco del sistema: si ese disco falla, "
                            "se pierden el original y la copia. Conviene un disco externo.")
        has_drivers = any(i.kind is ItemKind.DRIVER for i in items)
        if IS_WINDOWS and not is_admin() and (has_drivers or (wifi and self.cb_wifi_keys.isChecked())):
            warnings.append("Sin permisos de administrador no se pueden exportar los drivers "
                            "ni las claves Wi-Fi. Podés reiniciar la app como administrador.")
        dest_norm = os.path.normcase(os.path.abspath(dest))
        for r in self._scanned_roots:
            rn = os.path.normcase(os.path.abspath(r))
            if dest_norm == rn or dest_norm.startswith(rn.rstrip(os.sep) + os.sep):
                warnings.append("El destino está dentro de una carpeta que se recorrió. "
                                "La próxima búsqueda va a encontrar también el backup.")
                break
        if warnings:
            msg = "\n\n".join("• " + w for w in warnings) + "\n\n¿Continuar de todos modos?"
            if QMessageBox.question(self, APP_NAME, msg) != QMessageBox.StandardButton.Yes:
                return

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
        self._copy_started = time.monotonic()
        self._backup_worker = BackupWorker(items, options)
        self._backup_worker.progress.connect(self._on_copy_progress)
        self._backup_worker.log.connect(self._append_log)
        self._backup_worker.finished.connect(self._on_backup_finished)
        self._set_busy(True, scanning=False)
        self._thread = start_in_thread(self._backup_worker, self)

    def _cancel_backup(self) -> None:
        if self._backup_worker:
            self._backup_worker.cancel()
            self.copy_status.setText("Cancelando… (se termina el archivo actual y se guarda el informe)")

    def _on_copy_progress(self, p: CopyProgress) -> None:
        if p.bytes_total:
            frac = p.bytes_done / p.bytes_total
        else:
            frac = p.files_done / p.files_total if p.files_total else 0
        self.progress.setValue(int(min(frac, 1.0) * 1000))
        self.progress.setFormat(f"{frac * 100:.1f} %")
        elapsed = time.monotonic() - self._copy_started
        eta = ""
        if p.bytes_done and elapsed > 3 and p.bytes_total > p.bytes_done:
            rate = p.bytes_done / elapsed
            eta = f" · {format_size(rate)}/s · faltan ~{_fmt_duration((p.bytes_total - p.bytes_done) / rate)}"
        self.copy_status.setText(
            f"{p.phase}: {format_count(p.files_done)} de {format_count(p.files_total)} · "
            f"{format_size(p.bytes_done)} de {format_size(p.bytes_total)}{eta}<br>{_esc(_shorten(p.current, 120))}")

    def _on_backup_finished(self, r: CopyResult) -> None:
        self._last_worker = self._backup_worker
        self._backup_worker = None
        self._set_busy(False)
        elapsed = time.monotonic() - self._copy_started
        if not r.cancelled:
            self.progress.setValue(1000)
            self.progress.setFormat("100 %")
        title = "Backup cancelado" if r.cancelled else ("Backup terminado con errores" if r.failed
                                                        else "Backup terminado")
        text = (f"Archivos copiados: {format_count(r.copied)} ({format_size(r.bytes_copied)})\n"
                f"Ya existían (salteados): {format_count(r.skipped_existing)}\n"
                f"Perfiles de marcadores: {r.bookmarks_saved}\n"
                f"Drivers exportados: {r.drivers_exported}\n"
                f"Errores: {r.failed}\n"
                f"Duración: {_fmt_duration(elapsed)}\n\n"
                f"El detalle está en manifiesto.csv" + (" y errores.log" if r.failed else "") +
                " dentro de la carpeta del backup.")
        self.copy_status.setText(title + " · " + _fmt_duration(elapsed))
        box = QMessageBox(QMessageBox.Icon.Warning if r.failed else QMessageBox.Icon.Information,
                          title, text, parent=self)
        open_btn = box.addButton("Abrir carpeta del backup", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is open_btn and r.backup_dir and os.path.isdir(r.backup_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(r.backup_dir))
        self.name_edit.setText(default_backup_name())
        self._update_space_label()

    # ================================================================ varios
    def _set_busy(self, busy: bool, scanning: bool = False) -> None:
        self.btn_scan.setEnabled(not busy)
        self.btn_backup.setEnabled(not busy)
        self.btn_cancel_scan.setEnabled(busy and scanning)
        self.btn_cancel_backup.setEnabled(busy and not scanning)
        self.roots_list.setEnabled(not busy)
        if busy and not scanning:
            self.progress.setValue(0)
            self.progress.setFormat("0 %")

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {text}")
        if text.startswith("ERROR") and not self.btn_log.isChecked():
            self.btn_log.setText("Registro (hay errores)")

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
        self.cb_group.setChecked(s.value("group", True, type=bool))
        self.cb_verify.setChecked(s.value("verify", False, type=bool))
        self.spin_min_img.setValue(s.value("min_img_kb", cats.IMAGES.default_min_kb, type=int))
        extra_roots = s.value("extra_roots", [])
        if isinstance(extra_roots, str):
            extra_roots = [extra_roots]
        for r in extra_roots or []:
            if os.path.isdir(r):
                self._add_root_item(r, checked=False)
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
        s.setValue("group", self.cb_group.isChecked())
        s.setValue("verify", self.cb_verify.isChecked())
        s.setValue("min_img_kb", self.spin_min_img.value())
        default_roots = {os.path.normcase(users_root())} | {os.path.normcase(d.root) for d in list_drives()}
        extra = [self.roots_list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.roots_list.count())]
        s.setValue("extra_roots", [r for r in extra if os.path.normcase(r) not in default_roots])
        s.setValue("geometry", self.saveGeometry())

    def closeEvent(self, event) -> None:
        worker = self._backup_worker or self._scan_worker
        if worker is not None:
            msg = ("Hay un backup en curso. Si cerrás ahora va a quedar incompleto. ¿Cerrar igual?"
                   if self._backup_worker else "Hay una búsqueda en curso. ¿Cerrar igual?")
            if QMessageBox.question(self, APP_NAME, msg) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            worker.cancel()
            if self._thread is not None:
                try:
                    self._thread.quit()
                    self._thread.wait(10_000)
                except RuntimeError:
                    pass   # el hilo ya fue liberado
        self._save_settings()
        event.accept()


def _esc(text: str) -> str:
    import html
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
