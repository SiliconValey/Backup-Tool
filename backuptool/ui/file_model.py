"""Modelo de árbol para el explorador: Categoría → Extensión/grupo → Archivo.

Es un QAbstractItemModel propio (y no QStandardItemModel) para que siga
siendo rápido con cientos de miles de archivos: cada nodo guarda los totales
de su rama, así marcar o desmarcar un grupo no recorre el árbol entero.
"""

from __future__ import annotations

import os
import re
import time

from PySide6.QtCore import (QAbstractItemModel, QFileInfo, QModelIndex, QSortFilterProxyModel,
                            Qt, Signal)
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QFileIconProvider, QStyle

from ..core.categories import ALL_CATEGORIES, BOOKMARKS_LABEL, DRIVERS_LABEL
from ..core.models import FoundItem, ItemKind
from ..core.winutils import format_count, format_size

COL_NAME, COL_COUNT, COL_SIZE, COL_DATE, COL_PATH = range(5)
HEADERS = ["Nombre", "Archivos", "Tamaño", "Modificado", "Ubicación"]

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
ITEM_ROLE = Qt.ItemDataRole.UserRole + 2
LEVEL_ROLE = Qt.ItemDataRole.UserRole + 3

# Orden fijo de las categorías en el explorador
CATEGORY_ORDER = [c.label for c in ALL_CATEGORIES] + [BOOKMARKS_LABEL, DRIVERS_LABEL]

LEVEL_ROOT, LEVEL_CATEGORY, LEVEL_GROUP, LEVEL_ITEM = range(4)

_NCOLS = len(HEADERS)
_FLAGS_PLAIN = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
_FLAGS_CHECKABLE = _FLAGS_PLAIN | Qt.ItemFlag.ItemIsUserCheckable


_DIGITS = re.compile(r"\d+")


def _natural_key(text: str) -> str:
    """'foto 2' < 'foto 10': rellena los números con ceros para compararlos como texto."""
    return _DIGITS.sub(lambda m: m.group().zfill(12), text.casefold())


class Node:
    __slots__ = ("parent", "level", "label", "item", "children", "child_map", "row",
                 "count", "size", "checked_count", "checked_size", "checked")

    def __init__(self, parent: "Node | None", level: int, label: str = "",
                 item: FoundItem | None = None):
        self.parent = parent
        self.level = level
        self.label = label
        self.item = item
        self.children: list[Node] = []
        self.child_map: dict[str, Node] = {}
        self.row = 0
        self.count = 0
        self.size = 0
        self.checked_count = 0
        self.checked_size = 0
        self.checked = True

    def add_child(self, child: "Node") -> None:
        child.row = len(self.children)
        self.children.append(child)
        if child.level != LEVEL_ITEM:
            self.child_map[child.label] = child


class FoundItemsModel(QAbstractItemModel):
    selectionTotalsChanged = Signal(int, object)   # cantidad, bytes (object: puede pasar 2^31)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = Node(None, LEVEL_ROOT)
        self._icon_provider = QFileIconProvider()
        self._icon_cache: dict[str, QIcon] = {}
        style = QApplication.style()
        self._folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._special_icons = {
            BOOKMARKS_LABEL: style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon),
            DRIVERS_LABEL: style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
        }
        self._bold = QFont()
        self._bold.setBold(True)

    # ------------------------------------------------------------ estructura
    def _node(self, index: QModelIndex) -> Node:
        if index.isValid():
            return index.internalPointer()
        return self._root

    def index(self, row, column, parent=QModelIndex()):
        # Se llama cientos de miles de veces con grupos expandidos: camino corto
        node = parent.internalPointer() if parent.isValid() else self._root
        if row >= 0 and column < _NCOLS:
            try:
                return self.createIndex(row, column, node.children[row])
            except IndexError:
                pass
        return QModelIndex()

    def parent(self, index=QModelIndex()):  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        node: Node = index.internalPointer()
        p = node.parent
        if p is None or p is self._root:
            return QModelIndex()
        return self.createIndex(p.row, 0, p)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid() and parent.column() != 0:
            return 0
        return len(self._node(parent).children)

    def columnCount(self, parent=QModelIndex()):
        return len(HEADERS)

    def hasChildren(self, parent=QModelIndex()):
        return bool(self._node(parent).children)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return _FLAGS_CHECKABLE if index.column() == COL_NAME else _FLAGS_PLAIN

    # ----------------------------------------------------------------- datos
    def _check_state(self, node: Node) -> Qt.CheckState:
        if node.level == LEVEL_ITEM:
            return Qt.CheckState.Checked if node.checked else Qt.CheckState.Unchecked
        if node.checked_count == 0:
            return Qt.CheckState.Unchecked
        if node.checked_count == node.count:
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked

    def _icon_for(self, node: Node) -> QIcon:
        if node.level == LEVEL_CATEGORY:
            return self._special_icons.get(node.label, self._folder_icon)
        if node.level == LEVEL_GROUP:
            return self._folder_icon
        item = node.item
        assert item is not None
        if item.kind is not ItemKind.FILE:
            return self._special_icons.get(item.category, self._folder_icon)
        key = item.group
        icon = self._icon_cache.get(key)
        if icon is None:
            icon = self._icon_provider.icon(QFileInfo(item.path))
            self._icon_cache[key] = icon
        return icon

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: Node = index.internalPointer()
        col = index.column()
        item = node.item

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return item.name if item else node.label
            if col == COL_COUNT:
                return "" if item else format_count(node.count)
            if col == COL_SIZE:
                if item and item.kind is ItemKind.DRIVER:
                    return ""
                return format_size(item.size if item else node.size)
            if col == COL_DATE:
                if item and item.mtime:
                    return time.strftime("%Y-%m-%d %H:%M", time.localtime(item.mtime))
                return ""
            if col == COL_PATH:
                return os.path.dirname(item.path) if item else ""
            return None

        if role == Qt.ItemDataRole.CheckStateRole and col == COL_NAME:
            return self._check_state(node)

        if role == Qt.ItemDataRole.DecorationRole and col == COL_NAME:
            return self._icon_for(node)

        if role == Qt.ItemDataRole.ToolTipRole:
            if item:
                return item.path
            return f"{format_count(node.checked_count)} de {format_count(node.count)} marcados"

        if role == Qt.ItemDataRole.FontRole and node.level == LEVEL_CATEGORY:
            return self._bold

        if role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_COUNT, COL_SIZE):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == SORT_ROLE:
            if col == COL_NAME:
                return _natural_key(item.name if item else node.label)
            if col == COL_COUNT:
                return node.count
            if col == COL_SIZE:
                return item.size if item else node.size
            if col == COL_DATE:
                return item.mtime if item else 0.0
            if col == COL_PATH:
                return item.path.casefold() if item else ""

        if role == ITEM_ROLE:
            return item
        if role == LEVEL_ROLE:
            return node.level
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or not index.isValid():
            return False
        state = Qt.CheckState(value) if not isinstance(value, Qt.CheckState) else value
        self.set_checked(index, state == Qt.CheckState.Checked)
        return True

    # ------------------------------------------------------------- marcado
    def set_checked(self, index: QModelIndex, checked: bool) -> None:
        node = self._node(index)
        d_count, d_size = self._apply_check(node, checked)
        if node is not self._root:
            self._emit_subtree_changed(node, index)
        else:
            self._emit_subtree_changed(node, QModelIndex())
        self._propagate(node.parent, d_count, d_size)
        self._emit_totals()

    def set_all_checked(self, checked: bool) -> None:
        self.set_checked(QModelIndex(), checked)

    def _apply_check(self, node: Node, checked: bool) -> tuple[int, int]:
        if node.level == LEVEL_ITEM:
            if node.checked == checked:
                return 0, 0
            node.checked = checked
            sign = 1 if checked else -1
            size = node.item.size if node.item else 0
            return sign, sign * size
        d_count = d_size = 0
        for child in node.children:
            c, s = self._apply_check(child, checked)
            d_count += c
            d_size += s
        node.checked_count += d_count
        node.checked_size += d_size
        return d_count, d_size

    def _propagate(self, node: Node | None, d_count: int, d_size: int) -> None:
        while node is not None:
            node.checked_count += d_count
            node.checked_size += d_size
            if node is not self._root:
                idx = self.createIndex(node.row, COL_NAME, node)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.CheckStateRole])
            node = node.parent

    def _emit_subtree_changed(self, node: Node, index: QModelIndex) -> None:
        if index.isValid():
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self._emit_children_changed(node)

    def _emit_children_changed(self, node: Node) -> None:
        """Un dataChanged por rango de hijos (no uno por archivo)."""
        if not node.children:
            return
        first = self.createIndex(0, COL_NAME, node.children[0])
        last = self.createIndex(len(node.children) - 1, COL_NAME, node.children[-1])
        self.dataChanged.emit(first, last, [Qt.ItemDataRole.CheckStateRole])
        if node.level < LEVEL_GROUP:
            for child in node.children:
                self._emit_children_changed(child)

    def _emit_totals(self) -> None:
        self.selectionTotalsChanged.emit(self._root.checked_count, self._root.checked_size)

    # ------------------------------------------------------------- carga
    def clear(self) -> None:
        self.beginResetModel()
        self._root = Node(None, LEVEL_ROOT)
        self.endResetModel()
        self._emit_totals()

    def add_items(self, items: list[FoundItem]) -> None:
        """Agrega un lote de elementos (se llama varias veces durante la búsqueda)."""
        if not items:
            return
        grouped: dict[str, dict[str, list[FoundItem]]] = {}
        for it in items:
            grouped.setdefault(it.category, {}).setdefault(it.group, []).append(it)

        for cat_label, groups in grouped.items():
            cat = self._root.child_map.get(cat_label)
            if cat is None:
                pos = len(self._root.children)
                self.beginInsertRows(QModelIndex(), pos, pos)
                cat = Node(self._root, LEVEL_CATEGORY, cat_label)
                self._root.add_child(cat)
                self.endInsertRows()
            cat_idx = self.createIndex(cat.row, 0, cat)

            for group_label, group_items in groups.items():
                grp = cat.child_map.get(group_label)
                if grp is None:
                    pos = len(cat.children)
                    self.beginInsertRows(cat_idx, pos, pos)
                    grp = Node(cat, LEVEL_GROUP, group_label)
                    cat.add_child(grp)
                    self.endInsertRows()
                grp_idx = self.createIndex(grp.row, 0, grp)

                start = len(grp.children)
                self.beginInsertRows(grp_idx, start, start + len(group_items) - 1)
                added_size = 0
                for it in group_items:
                    grp.add_child(Node(grp, LEVEL_ITEM, item=it))
                    added_size += it.size
                self.endInsertRows()

                n = len(group_items)
                for node in (grp, cat, self._root):
                    node.count += n
                    node.size += added_size
                    node.checked_count += n
                    node.checked_size += added_size
                self.dataChanged.emit(self.createIndex(grp.row, 0, grp),
                                      self.createIndex(grp.row, COL_SIZE, grp))
            self.dataChanged.emit(self.createIndex(cat.row, 0, cat),
                                  self.createIndex(cat.row, COL_SIZE, cat))
        self._emit_totals()

    # ------------------------------------------------------------ orden
    def root_node(self) -> Node:
        return self._root

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        self._sort_column, self._sort_order = column, order
        if not self._root.children:
            return
        self.layoutAboutToBeChanged.emit()
        old = self.persistentIndexList()
        saved = [(i.internalPointer(), i.column()) for i in old]
        reverse = order == Qt.SortOrder.DescendingOrder

        def key(node: Node):
            item = node.item
            if column == COL_COUNT:
                return node.count
            if column == COL_SIZE:
                return item.size if item else node.size
            if column == COL_DATE:
                return item.mtime if item else 0.0
            if column == COL_PATH:
                return item.path.casefold() if item else ""
            return _natural_key(item.name if item else node.label)

        def order_cat(node: Node) -> int:
            return CATEGORY_ORDER.index(node.label) if node.label in CATEGORY_ORDER else 99

        # Las categorías mantienen siempre su orden fijo
        self._root.children.sort(key=order_cat)
        self._renumber(self._root)
        for cat in self._root.children:
            cat.children.sort(key=key, reverse=reverse)
            self._renumber(cat)
            for grp in cat.children:
                grp.children.sort(key=key, reverse=reverse)
                self._renumber(grp)

        new = [self.createIndex(node.row, col, node) if node is not None else QModelIndex()
               for node, col in saved]
        self.changePersistentIndexList(old, new)
        self.layoutChanged.emit()

    @staticmethod
    def _renumber(node: Node) -> None:
        for i, child in enumerate(node.children):
            child.row = i

    # ------------------------------------------------------------ consultas
    def checked_items(self) -> list[FoundItem]:
        out: list[FoundItem] = []
        for cat in self._root.children:
            for grp in cat.children:
                out.extend(n.item for n in grp.children if n.checked and n.item)
        return out

    def totals(self) -> tuple[int, int, int, int]:
        r = self._root
        return r.count, r.size, r.checked_count, r.checked_size

    def category_summary(self) -> list[tuple[str, int, int]]:
        def order(label: str) -> int:
            return CATEGORY_ORDER.index(label) if label in CATEGORY_ORDER else 99
        return sorted(((c.label, c.count, c.size) for c in self._root.children),
                      key=lambda t: order(t[0]))


class FoundItemsProxy(QSortFilterProxyModel):
    """Filtra por texto en nombre o ruta. El orden lo resuelve el modelo de origen
    (ordenar 200.000 filas con lessThan en Python tarda más de un minuto;
    con list.sort tarda menos de un segundo)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.setRecursiveFilteringEnabled(True)
        self.setDynamicSortFilter(False)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        model = self.sourceModel()
        if model is not None:
            model.sort(column, order)

    def set_filter_text(self, text: str) -> None:
        if hasattr(self, "beginFilterChange"):      # Qt 6.10+
            self.beginFilterChange()
            self._text = text.strip().casefold()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self._text = text.strip().casefold()
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._text:
            return True
        parent: Node = (source_parent.internalPointer() if source_parent.isValid()
                        else self.sourceModel().root_node())
        item = parent.children[source_row].item
        if item is None:
            return False   # los grupos se muestran si algún hijo coincide (filtro recursivo)
        return self._text in item.path.casefold()
