"""Marcadores (favoritos) de los navegadores.

- Navegadores basados en Chromium (Chrome, Edge, Brave, Vivaldi, Opera):
  archivo JSON ``Bookmarks`` dentro de cada perfil.
- Firefox: tabla ``moz_bookmarks`` dentro de ``places.sqlite``.

Además de copiar el archivo original, se exporta cada perfil a HTML en el
formato estándar "Netscape Bookmark File", que cualquier navegador importa.
"""

from __future__ import annotations

import html
import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field

from .categories import BOOKMARKS_LABEL
from .models import FoundItem, ItemKind

# (nombre visible, ruta relativa a AppData\Local o AppData\Roaming, base)
CHROMIUM_BROWSERS: list[tuple[str, str, str]] = [
    ("Google Chrome", r"Google\Chrome\User Data", "Local"),
    ("Microsoft Edge", r"Microsoft\Edge\User Data", "Local"),
    ("Brave", r"BraveSoftware\Brave-Browser\User Data", "Local"),
    ("Vivaldi", r"Vivaldi\User Data", "Local"),
    ("Chromium", r"Chromium\User Data", "Local"),
    ("Opera", r"Opera Software\Opera Stable", "Roaming"),
    ("Opera GX", r"Opera Software\Opera GX Stable", "Roaming"),
]
FIREFOX_PROFILES = r"Mozilla\Firefox\Profiles"

WEBKIT_EPOCH_OFFSET = 11644473600  # segundos entre 1601-01-01 y 1970-01-01


@dataclass
class BookmarkNode:
    title: str
    url: str | None = None          # None => carpeta
    add_date: int = 0               # timestamp unix (segundos)
    children: list["BookmarkNode"] = field(default_factory=list)

    @property
    def is_folder(self) -> bool:
        return self.url is None

    def count_urls(self) -> int:
        if not self.is_folder:
            return 1
        return sum(c.count_urls() for c in self.children)


# ------------------------------------------------------------------ búsqueda
def _sep(path: str) -> str:
    return path.replace("\\", os.sep)


def _chromium_profile_dirs(user_data: str) -> list[str]:
    """Perfiles dentro de 'User Data': Default, Profile 1, Profile 2..."""
    # Opera guarda el perfil directamente en la carpeta, sin subperfiles
    if os.path.isfile(os.path.join(user_data, "Bookmarks")):
        return [user_data]
    found = []
    try:
        for entry in os.scandir(user_data):
            if entry.is_dir() and (entry.name == "Default" or entry.name.startswith("Profile ")):
                if os.path.isfile(os.path.join(entry.path, "Bookmarks")):
                    found.append(entry.path)
    except OSError:
        pass
    return sorted(found)


def _user_dirs(users_root: str) -> list[tuple[str, str]]:
    """(nombre de usuario, carpeta) de cada perfil de Windows con AppData."""
    result = []
    try:
        for entry in os.scandir(users_root):
            if entry.is_dir(follow_symlinks=False) and os.path.isdir(os.path.join(entry.path, "AppData")):
                result.append((entry.name, entry.path))
    except OSError:
        pass
    return sorted(result)


def find_bookmark_sources(users_root: str) -> list[FoundItem]:
    """Busca los archivos de marcadores de todos los usuarios y navegadores."""
    items: list[FoundItem] = []
    for user, home in _user_dirs(users_root):
        appdata = {
            "Local": os.path.join(home, "AppData", "Local"),
            "Roaming": os.path.join(home, "AppData", "Roaming"),
        }
        for browser, rel, base in CHROMIUM_BROWSERS:
            user_data = os.path.join(appdata[base], _sep(rel))
            if not os.path.isdir(user_data):
                continue
            for prof in _chromium_profile_dirs(user_data):
                path = os.path.join(prof, "Bookmarks")
                profile = os.path.basename(prof) if prof != user_data else "Default"
                items.append(_make_item(path, browser, user, profile, "chromium"))
        ff = os.path.join(appdata["Roaming"], _sep(FIREFOX_PROFILES))
        if os.path.isdir(ff):
            try:
                for entry in sorted(os.scandir(ff), key=lambda e: e.name):
                    db = os.path.join(entry.path, "places.sqlite")
                    if entry.is_dir() and os.path.isfile(db):
                        items.append(_make_item(db, "Mozilla Firefox", user, entry.name, "firefox"))
            except OSError:
                pass
    return items


def _make_item(path: str, browser: str, user: str, profile: str, fmt: str) -> FoundItem:
    try:
        st = os.stat(path)
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0.0
    count = None
    try:
        count = sum(n.count_urls() for n in read_bookmarks(path, fmt))
    except Exception:
        pass
    label = f"{user} · perfil {profile}"
    if count is not None:
        label += f" ({count} marcadores)"
    return FoundItem(
        path=path, size=size, mtime=mtime, category=BOOKMARKS_LABEL,
        group=browser, kind=ItemKind.BOOKMARK, display_name=label,
        extra={"browser": browser, "user": user, "profile": profile,
               "format": fmt, "count": count},
    )


# ------------------------------------------------------------------ lectura
def read_bookmarks(path: str, fmt: str) -> list[BookmarkNode]:
    if fmt == "chromium":
        return read_chromium(path)
    if fmt == "firefox":
        return read_firefox(path)
    raise ValueError(fmt)


def _webkit_to_unix(value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    if v <= 0:
        return 0
    return max(0, int(v / 1_000_000 - WEBKIT_EPOCH_OFFSET))


def read_chromium(path: str) -> list[BookmarkNode]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    def convert(node: dict) -> BookmarkNode:
        if node.get("type") == "url":
            return BookmarkNode(node.get("name", ""), node.get("url", ""),
                                _webkit_to_unix(node.get("date_added")))
        folder = BookmarkNode(node.get("name", ""), None, _webkit_to_unix(node.get("date_added")))
        folder.children = [convert(c) for c in node.get("children", [])]
        return folder

    roots = data.get("roots", {})
    names = {"bookmark_bar": "Barra de marcadores", "other": "Otros marcadores",
             "synced": "Marcadores del móvil"}
    result = []
    for key, label in names.items():
        if key in roots:
            node = convert(roots[key])
            node.title = node.title or label
            if node.children:
                result.append(node)
    return result


def read_firefox(path: str) -> list[BookmarkNode]:
    # Firefox bloquea la base mientras está abierto: se trabaja sobre una copia.
    tmpdir = tempfile.mkdtemp(prefix="bt_ff_")
    try:
        tmp_db = os.path.join(tmpdir, "places.sqlite")
        shutil.copy2(path, tmp_db)
        wal = path + "-wal"
        if os.path.isfile(wal):
            shutil.copy2(wal, tmp_db + "-wal")
        con = sqlite3.connect(tmp_db)
        try:
            rows = con.execute(
                """SELECT b.id, b.type, b.parent, b.position, b.title, b.dateAdded,
                          b.guid, p.url
                   FROM moz_bookmarks b LEFT JOIN moz_places p ON b.fk = p.id"""
            ).fetchall()
        finally:
            con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    by_parent: dict[int, list[tuple]] = {}
    by_guid: dict[str, tuple] = {}
    for row in rows:
        by_parent.setdefault(row[2], []).append(row)
        by_guid[row[6]] = row
    for children in by_parent.values():
        children.sort(key=lambda r: r[3] or 0)

    def build(row) -> BookmarkNode | None:
        _id, btype, _parent, _pos, title, added, _guid, url = row
        add_date = int((added or 0) / 1_000_000)
        if btype == 1:
            if not url or url.startswith("place:"):
                return None
            return BookmarkNode(title or url, url, add_date)
        if btype == 2:
            node = BookmarkNode(title or "", None, add_date)
            for child in by_parent.get(_id, []):
                built = build(child)
                if built is not None:
                    node.children.append(built)
            return node
        return None   # separadores

    roots = [("toolbar_____", "Barra de marcadores"), ("menu________", "Menú de marcadores"),
             ("unfiled_____", "Otros marcadores"), ("mobile______", "Marcadores del móvil")]
    result = []
    for guid, label in roots:
        row = by_guid.get(guid)
        if row is None:
            continue
        node = build(row)
        if node and node.children:
            node.title = label
            result.append(node)
    return result


# ------------------------------------------------------------------ exportar
def to_netscape_html(nodes: list[BookmarkNode], title: str = "Marcadores") -> str:
    out = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- Generado por BackupTool. Se puede importar desde cualquier navegador. -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        f"<TITLE>{html.escape(title)}</TITLE>",
        f"<H1>{html.escape(title)}</H1>",
        "<DL><p>",
    ]

    def emit(node: BookmarkNode, depth: int) -> None:
        pad = "    " * depth
        date = f' ADD_DATE="{node.add_date}"' if node.add_date else ""
        if node.is_folder:
            out.append(f"{pad}<DT><H3{date}>{html.escape(node.title)}</H3>")
            out.append(f"{pad}<DL><p>")
            for child in node.children:
                emit(child, depth + 1)
            out.append(f"{pad}</DL><p>")
        else:
            out.append(f'{pad}<DT><A HREF="{html.escape(node.url or "", quote=True)}"{date}>'
                       f"{html.escape(node.title)}</A>")

    for n in nodes:
        emit(n, 1)
    out.append("</DL><p>")
    return "\n".join(out) + "\n"


def backup_bookmark(item: FoundItem, dest_dir: str) -> tuple[str, int]:
    """Copia el archivo original y genera marcadores.html. Devuelve (carpeta, cantidad)."""
    os.makedirs(dest_dir, exist_ok=True)
    fmt = item.extra.get("format", "chromium")
    shutil.copy2(item.path, os.path.join(dest_dir, os.path.basename(item.path)))
    if fmt == "firefox" and os.path.isfile(item.path + "-wal"):
        shutil.copy2(item.path + "-wal", os.path.join(dest_dir, "places.sqlite-wal"))
    nodes = read_bookmarks(item.path, fmt)
    title = f"Marcadores de {item.extra.get('browser', '')} — {item.extra.get('user', '')} " \
            f"({time.strftime('%Y-%m-%d')})"
    with open(os.path.join(dest_dir, "marcadores.html"), "w", encoding="utf-8") as fh:
        fh.write(to_netscape_html(nodes, title))
    return dest_dir, sum(n.count_urls() for n in nodes)
