"""Recorrido de disco: encuentra archivos de las categorías habilitadas.

Usa ``os.scandir`` con una pila explícita (sin recursión), que en Windows
obtiene tamaño, fecha y atributos en la misma llamada que lista la carpeta.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator

from . import categories as cats
from .models import FoundItem, ItemKind, ScanStats
from .winutils import (CLOUD_ONLY_MASK, FILE_ATTRIBUTE_REPARSE_POINT,
                       FILE_ATTRIBUTE_SYSTEM, IS_WINDOWS)

ProgressCallback = Callable[[ScanStats, str], None]


@dataclass
class ScanOptions:
    roots: list[str]
    enabled_categories: set[str] = field(
        default_factory=lambda: {c.key for c in cats.ALL_CATEGORIES})
    # Tamaño mínimo en KB por categoría; si falta se usa el de la categoría.
    min_kb: dict[str, int] = field(default_factory=dict)
    excluded_dir_names: set[str] = field(
        default_factory=lambda: set(cats.DEFAULT_EXCLUDED_DIRS))
    # Rutas completas a excluir (por ejemplo la carpeta de destino del backup).
    excluded_paths: list[str] = field(default_factory=list)
    skip_cloud_only: bool = True
    skip_system_files: bool = True


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003   # junctions ("Mis documentos", "All Users"...)
IO_REPARSE_TAG_SYMLINK = 0xA000000C


def _is_link_dir(entry: os.DirEntry) -> bool:
    """True para symlinks y junctions, que llevarían a recorrer algo dos veces o en bucle.

    Ojo: las carpetas de OneDrive también son "reparse points" (con otra
    etiqueta) y esas sí hay que recorrerlas.
    """
    if entry.is_symlink():
        return True
    if IS_WINDOWS:
        try:
            st = entry.stat(follow_symlinks=False)
            if not st.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT:
                return False
            tag = getattr(st, "st_reparse_tag", 0) or os.lstat(entry.path).st_reparse_tag
            return tag in (IO_REPARSE_TAG_MOUNT_POINT, IO_REPARSE_TAG_SYMLINK)
        except OSError:
            return True
    return False


class Scanner:
    def __init__(self, options: ScanOptions,
                 cancel_event: threading.Event | None = None,
                 progress: ProgressCallback | None = None,
                 progress_interval: float = 0.15):
        self.opt = options
        self.cancel_event = cancel_event or threading.Event()
        self.progress = progress
        self.progress_interval = progress_interval
        self.stats = ScanStats()
        self._ext_map = cats.build_extension_map(options.enabled_categories)
        self._min_bytes = {
            c.key: options.min_kb.get(c.key, c.default_min_kb) * 1024
            for c in cats.ALL_CATEGORIES
        }
        self._excluded_names = {n.casefold() for n in options.excluded_dir_names}
        self._excluded_paths = {_norm(p) for p in options.excluded_paths if p}
        self._saved_games = cats.SAVED_GAMES.key in options.enabled_categories
        self._last_report = 0.0

    # ------------------------------------------------------------------ API
    def scan(self) -> Iterator[FoundItem]:
        """Generador de elementos encontrados. Se puede cancelar con cancel_event."""
        start = time.monotonic()
        seen_roots: set[str] = set()
        for root in self.opt.roots:
            nroot = _norm(root)
            # Evita recorrer dos veces si una raíz está dentro de otra
            if any(nroot == r or nroot.startswith(r.rstrip(os.sep) + os.sep) for r in seen_roots):
                continue
            seen_roots.add(nroot)
            yield from self._walk(root)
            if self.cancel_event.is_set():
                break
        self.stats.cancelled = self.cancel_event.is_set()
        self.stats.seconds = time.monotonic() - start
        self._report("", force=True)

    # ------------------------------------------------------------ internals
    def _report(self, current: str, force: bool = False) -> None:
        if not self.progress:
            return
        now = time.monotonic()
        if force or now - self._last_report >= self.progress_interval:
            self._last_report = now
            self.progress(self.stats, current)

    def _skip_dir(self, entry: os.DirEntry) -> bool:
        if entry.name.casefold() in self._excluded_names:
            return True
        if self._excluded_paths and _norm(entry.path) in self._excluded_paths:
            return True
        return _is_link_dir(entry)

    def _walk(self, root: str) -> Iterator[FoundItem]:
        # Cada elemento de la pila: (carpeta, categoría forzada o None)
        start_forced = None
        if self._saved_games and os.path.basename(os.path.normpath(root)).casefold() == cats.SAVED_GAMES_DIRNAME:
            start_forced = cats.SAVED_GAMES
        stack: list[tuple[str, cats.Category | None]] = [(root, start_forced)]
        while stack:
            if self.cancel_event.is_set():
                return
            folder, forced = stack.pop()
            try:
                with os.scandir(folder) as it:
                    entries = list(it)
            except OSError:
                self.stats.errors += 1
                continue
            self.stats.dirs_scanned += 1
            self._report(folder)
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if self._skip_dir(entry):
                            continue
                        child_forced = forced
                        if (child_forced is None and self._saved_games
                                and entry.name.casefold() == cats.SAVED_GAMES_DIRNAME):
                            child_forced = cats.SAVED_GAMES
                        stack.append((entry.path, child_forced))
                    elif entry.is_file(follow_symlinks=False):
                        self.stats.files_seen += 1
                        item = self._classify(entry, forced)
                        if item is not None:
                            self.stats.items_found += 1
                            self.stats.bytes_found += item.size
                            yield item
                except OSError:
                    self.stats.errors += 1

    def _classify(self, entry: os.DirEntry, forced: cats.Category | None) -> FoundItem | None:
        name = entry.name
        ext = os.path.splitext(name)[1].lower()
        if forced is not None:
            cat = forced
        else:
            cat = self._ext_map.get(ext)
            if cat is None:
                return None
        st = entry.stat(follow_symlinks=False)
        if IS_WINDOWS:
            attrs = st.st_file_attributes
            if self.opt.skip_cloud_only and attrs & CLOUD_ONLY_MASK:
                self.stats.skipped_cloud += 1
                return None
            if self.opt.skip_system_files and attrs & FILE_ATTRIBUTE_SYSTEM:
                return None
        if name.casefold() in ("desktop.ini", "thumbs.db"):
            return None
        if st.st_size < self._min_bytes.get(cat.key, 0):
            return None
        group = ext if ext else "(sin extensión)"
        return FoundItem(
            path=entry.path, size=st.st_size, mtime=st.st_mtime,
            category=cat.label, group=group, kind=ItemKind.FILE,
        )


def scan_all(options: ScanOptions) -> tuple[list[FoundItem], ScanStats]:
    """Atajo sin interfaz: recorre todo y devuelve la lista completa."""
    scanner = Scanner(options)
    items = list(scanner.scan())
    return items, scanner.stats
