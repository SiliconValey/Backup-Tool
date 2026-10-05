"""Categorías de archivos a respaldar y carpetas que se excluyen del recorrido."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Category:
    key: str
    label: str
    extensions: frozenset[str]
    # Tamaño mínimo por defecto: evita iconos, miniaturas y sonidos del sistema.
    default_min_kb: int = 0
    description: str = ""


IMAGES = Category(
    "images", "Imágenes",
    frozenset({
        ".jpg", ".jpeg", ".jpe", ".png", ".gif", ".bmp", ".tif", ".tiff",
        ".webp", ".heic", ".heif", ".avif", ".psd", ".svg",
        # RAW de cámaras
        ".raw", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf",
    }),
    default_min_kb=10,
    description="Fotos e imágenes (se ignoran las menores a 10 KB, suelen ser iconos)",
)

AUDIO = Category(
    "audio", "Audio",
    frozenset({
        ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".oga", ".opus",
        ".wma", ".aiff", ".aif", ".alac", ".mid", ".midi", ".amr",
    }),
    default_min_kb=30,
    description="Música, grabaciones y notas de voz",
)

VIDEO = Category(
    "video", "Videos",
    frozenset({
        ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
        ".mpg", ".mpeg", ".3gp", ".vob", ".mts", ".m2ts",
    }),
    description="Videos y grabaciones de cámara",
)

DOCUMENTS = Category(
    "documents", "Documentos",
    frozenset({
        ".pdf", ".doc", ".docx", ".docm", ".xls", ".xlsx", ".xlsm", ".ppt",
        ".pptx", ".odt", ".ods", ".odp", ".rtf", ".txt", ".csv", ".md",
        ".epub", ".mobi", ".pub", ".vsd", ".vsdx", ".one", ".accdb", ".mdb",
    }),
    description="Office, PDF, texto, libros electrónicos",
)

MAIL = Category(
    "mail", "Correo",
    frozenset({".pst", ".eml", ".msg", ".mbox", ".vcf", ".ics"}),
    description="Archivos de Outlook (.pst), correos sueltos, contactos y calendarios",
)

SECURITY = Category(
    "security", "Claves y certificados",
    frozenset({".kdbx", ".kdb", ".pfx", ".p12", ".cer", ".crt", ".pem", ".ppk", ".asc", ".gpg"}),
    description="Bases de KeePass, certificados digitales y claves",
)

# Categoría especial: todo lo que esté dentro de una carpeta "Saved Games".
SAVED_GAMES = Category(
    "saved_games", "Partidas guardadas",
    frozenset(),
    description="Todo el contenido de las carpetas 'Saved Games' de cada usuario",
)

FILE_CATEGORIES: tuple[Category, ...] = (IMAGES, AUDIO, VIDEO, DOCUMENTS, MAIL, SECURITY)
ALL_CATEGORIES: tuple[Category, ...] = FILE_CATEGORIES + (SAVED_GAMES,)

BOOKMARKS_LABEL = "Marcadores"
DRIVERS_LABEL = "Drivers"

# Carpetas cuyo nombre se excluye en cualquier nivel del recorrido.
# AppData se excluye porque está llena de cachés; los marcadores de los
# navegadores se buscan por ruta conocida en browsers.py.
DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset({
    "$recycle.bin", "system volume information", "windows", "program files",
    "program files (x86)", "programdata", "appdata", "$windows.~bt",
    "$windows.~ws", "$winreagent", "$sysreset", "recovery", "perflogs",
    "msocache", "config.msi", "onedrivetemp",
    # Carpetas de desarrollo: miles de archivos sin valor para un backup personal
    "node_modules", ".git", ".svn", "__pycache__", ".venv", "venv",
    "site-packages", ".gradle", ".m2", ".nuget", ".cache", ".tox", ".idea",
})

SAVED_GAMES_DIRNAME = "saved games"


def build_extension_map(enabled_keys: set[str]) -> dict[str, Category]:
    """Devuelve {extension: Category} sólo para las categorías habilitadas."""
    ext_map: dict[str, Category] = {}
    for cat in FILE_CATEGORIES:
        if cat.key in enabled_keys:
            for ext in cat.extensions:
                ext_map[ext] = cat
    return ext_map


def category_by_key(key: str) -> Category:
    for cat in ALL_CATEGORIES:
        if cat.key == key:
            return cat
    raise KeyError(key)
