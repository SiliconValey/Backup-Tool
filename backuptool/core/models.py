"""Estructuras de datos compartidas entre el núcleo y la interfaz."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ItemKind(str, Enum):
    FILE = "file"          # archivo común (foto, audio, documento...)
    BOOKMARK = "bookmark"  # archivo de marcadores de un navegador
    DRIVER = "driver"      # paquete de driver de terceros (oemNN.inf)


@dataclass(slots=True)
class FoundItem:
    """Un elemento encontrado durante la búsqueda.

    ``category`` es el primer nivel del explorador (Imágenes, Audio...) y
    ``group`` el segundo: la extensión para archivos comunes, el navegador
    para marcadores y la clase de dispositivo para drivers.
    """

    path: str
    size: int
    mtime: float
    category: str
    group: str
    kind: ItemKind = ItemKind.FILE
    display_name: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        if self.display_name:
            return self.display_name
        import os
        return os.path.basename(self.path)


@dataclass(slots=True)
class ScanStats:
    dirs_scanned: int = 0
    files_seen: int = 0
    items_found: int = 0
    bytes_found: int = 0
    errors: int = 0
    skipped_cloud: int = 0
    cancelled: bool = False
    seconds: float = 0.0


@dataclass(slots=True)
class CopyResult:
    copied: int = 0
    skipped_existing: int = 0
    failed: int = 0
    bytes_copied: int = 0
    drivers_exported: int = 0
    bookmarks_saved: int = 0
    cancelled: bool = False
    backup_dir: str = ""
    errors: list[str] = field(default_factory=list)
