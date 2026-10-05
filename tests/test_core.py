"""Pruebas del núcleo (se ejecutan en cualquier sistema): python -m pytest"""

import json
import os
import sqlite3
import threading

import pytest

from backuptool.core import browsers, drivers
from backuptool.core.categories import BOOKMARKS_LABEL
from backuptool.core.copier import (BackupRunner, CopyOptions, relative_from_absolute,
                                    safe_name)
from backuptool.core.models import ItemKind
from backuptool.core.scanner import ScanOptions, Scanner, scan_all


def write(path, size=0, data=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data if data is not None else os.urandom(size))
    return path


@pytest.fixture
def fake_users(tmp_path):
    u = tmp_path / "Users"
    chris = u / "chris"
    write(str(chris / "Pictures" / "playa.JPG"), 50_000)
    write(str(chris / "Pictures" / "icono.png"), 2_000)            # < 10 KB: se ignora
    write(str(chris / "Music" / "tema.mp3"), 200_000)
    write(str(chris / "Videos" / "cumple.mp4"), 300_000)
    write(str(chris / "Documents" / "tesis.docx"), 1_000)
    write(str(chris / "Documents" / "notas.xyz"), 1_000)           # extensión desconocida
    write(str(chris / "Documents" / "proyecto" / "node_modules" / "x.png"), 50_000)
    write(str(chris / "AppData" / "Local" / "cache" / "foto.jpg"), 50_000)
    write(str(chris / "Saved Games" / "Juego" / "slot1.sav"), 500)
    write(str(chris / "Documents" / "Outlook Files" / "correo.pst"), 5_000)
    return u


def test_scanner_categories_and_exclusions(fake_users):
    items, stats = scan_all(ScanOptions(roots=[str(fake_users)]))
    by_name = {os.path.basename(i.path): i for i in items}
    assert set(by_name) == {"playa.JPG", "tema.mp3", "cumple.mp4", "tesis.docx",
                            "slot1.sav", "correo.pst"}
    assert by_name["playa.JPG"].category == "Imágenes"
    assert by_name["playa.JPG"].group == ".jpg"
    assert by_name["slot1.sav"].category == "Partidas guardadas"
    assert by_name["correo.pst"].category == "Correo"
    assert stats.items_found == 6
    assert stats.dirs_scanned > 5


def test_scanner_disabled_category_and_min_size(fake_users):
    opts = ScanOptions(roots=[str(fake_users)], enabled_categories={"images"},
                       min_kb={"images": 0})
    items, _ = scan_all(opts)
    names = sorted(os.path.basename(i.path) for i in items)
    assert names == ["icono.png", "playa.JPG"]


def test_scanner_excludes_destination(fake_users):
    dest = fake_users / "chris" / "Videos"
    items, _ = scan_all(ScanOptions(roots=[str(fake_users)], excluded_paths=[str(dest)]))
    assert not any(i.path.endswith("cumple.mp4") for i in items)


def test_scanner_nested_roots_not_duplicated(fake_users):
    items, _ = scan_all(ScanOptions(roots=[str(fake_users), str(fake_users / "chris")]))
    paths = [i.path for i in items]
    assert len(paths) == len(set(paths))


def test_scanner_cancel(fake_users):
    ev = threading.Event()
    ev.set()
    items = list(Scanner(ScanOptions(roots=[str(fake_users)]), cancel_event=ev).scan())
    assert items == []


# ------------------------------------------------------------------ navegadores
def make_chromium(users, user="chris", profile="Default"):
    data = {"roots": {
        "bookmark_bar": {"type": "folder", "name": "Barra", "children": [
            {"type": "url", "name": "ISFT 179", "url": "https://isft179.example/",
             "date_added": "13300000000000000"},
            {"type": "folder", "name": "Python & Qt", "children": [
                {"type": "url", "name": "PySide6 <docs>", "url": "https://doc.qt.io/qtforpython-6/?a=1&b=2"},
            ]},
        ]},
        "other": {"type": "folder", "name": "", "children": []},
    }}
    path = users / user / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / profile / "Bookmarks"
    write(str(path), data=json.dumps(data).encode())
    return path


def make_firefox(users, user="chris"):
    prof = users / user / "AppData" / "Roaming" / "Mozilla" / "Firefox" / "Profiles" / "abc.default-release"
    os.makedirs(prof)
    db = prof / "places.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INT, fk INT, parent INT,
                                    position INT, title TEXT, dateAdded INT, guid TEXT);
        INSERT INTO moz_places VALUES (1,'https://www.python.org/'),(2,'place:sort=8');
        INSERT INTO moz_bookmarks VALUES
            (1,2,NULL,0,0,'',0,'root________'),
            (2,2,NULL,1,0,'menu',0,'menu________'),
            (3,2,NULL,1,1,'toolbar',0,'toolbar_____'),
            (4,2,NULL,1,2,'tags',0,'tags________'),
            (5,1,1,3,0,'Python',1700000000000000,'aaaaaaaaaaaa'),
            (6,1,2,3,1,'Más visitados',0,'bbbbbbbbbbbb');
    """)
    con.commit()
    con.close()
    return db


def test_find_and_export_bookmarks(fake_users, tmp_path):
    make_chromium(fake_users)
    make_chromium(fake_users, profile="Profile 1")
    make_firefox(fake_users)
    items = browsers.find_bookmark_sources(str(fake_users))
    assert [(i.group, i.extra["profile"]) for i in items] == [
        ("Google Chrome", "Default"), ("Google Chrome", "Profile 1"),
        ("Mozilla Firefox", "abc.default-release")]
    assert all(i.kind is ItemKind.BOOKMARK and i.category == BOOKMARKS_LABEL for i in items)
    assert items[0].extra["count"] == 2
    assert items[2].extra["count"] == 1   # el "place:" se descarta

    out = tmp_path / "out"
    folder, count = browsers.backup_bookmark(items[0], str(out))
    html_text = (out / "marcadores.html").read_text(encoding="utf-8")
    assert count == 2
    assert "<!DOCTYPE NETSCAPE-Bookmark-file-1>" in html_text
    assert "PySide6 &lt;docs&gt;" in html_text
    assert "a=1&amp;b=2" in html_text
    assert "Python &amp; Qt" in html_text
    assert (out / "Bookmarks").exists()


def test_firefox_html(fake_users, tmp_path):
    db = make_firefox(fake_users)
    nodes = browsers.read_firefox(str(db))
    assert nodes[0].title == "Barra de marcadores"
    assert nodes[0].children[0].url == "https://www.python.org/"
    assert nodes[0].children[0].add_date == 1700000000


# ---------------------------------------------------------------------- drivers
INF_SAMPLE = """\
; comentario
[Version]
Signature="$WINDOWS NT$"
Class=Display
ClassGuid={4d36e968-e325-11ce-bfc1-08002be10318}
Provider=%NVIDIA%
DriverVer=08/14/2024,32.0.15.6094

[Strings]
NVIDIA = "NVIDIA"
"""


def test_list_drivers(tmp_path):
    write(str(tmp_path / "oem10.inf"), data=INF_SAMPLE.encode("utf-16"))
    write(str(tmp_path / "oem2.inf"), data=b"[Version]\nClass=Net\nProvider=Realtek\n")
    write(str(tmp_path / "machine.inf"), data=b"[Version]\nClass=System\n")
    items = drivers.list_third_party_drivers(str(tmp_path))
    assert [i.extra["inf"] for i in items] == ["oem2.inf", "oem10.inf"]
    assert items[1].group == "Video / gráficos"
    assert items[1].extra["provider"] == "NVIDIA"
    assert items[1].extra["version"] == "32.0.15.6094"
    assert items[0].group == "Red"


# ----------------------------------------------------------------------- copia
def test_relative_paths():
    assert relative_from_absolute("/home/x/a.jpg") == os.path.join("home", "x", "a.jpg")
    assert safe_name('a:b*c?') == "a_b_c_"


def test_backup_run_and_resume(fake_users, tmp_path):
    make_chromium(fake_users)
    items, _ = scan_all(ScanOptions(roots=[str(fake_users)]))
    items += browsers.find_bookmark_sources(str(fake_users))
    dest = tmp_path / "pendrive"
    dest.mkdir()
    logs = []
    opts = CopyOptions(dest_root=str(dest), backup_name="Backup_test", verify=True,
                       wifi_profiles=False, programs_list=False)
    res = BackupRunner(items, opts, log=logs.append).run()
    assert res.copied == 6 and res.failed == 0 and res.bookmarks_saved == 1
    root = dest / "Backup_test"
    src_rel = relative_from_absolute(str(fake_users / "chris" / "Pictures" / "playa.JPG"))
    copied = root / "Imágenes" / src_rel
    assert copied.read_bytes() == (fake_users / "chris" / "Pictures" / "playa.JPG").read_bytes()
    assert (root / "manifiesto.csv").exists()
    assert (root / "Marcadores" / "Google Chrome" / "chris" / "Default" / "marcadores.html").exists()
    assert not list(root.rglob("*.bt_part"))

    # Segunda ejecución: todo ya existe
    res2 = BackupRunner(items, opts).run()
    assert res2.copied == 0 and res2.skipped_existing == 6


def test_backup_cancel(fake_users, tmp_path):
    items, _ = scan_all(ScanOptions(roots=[str(fake_users)]))
    ev = threading.Event()
    ev.set()
    opts = CopyOptions(dest_root=str(tmp_path), backup_name="b",
                       wifi_profiles=False, programs_list=False)
    res = BackupRunner(items, opts, cancel_event=ev).run()
    assert res.cancelled and res.copied == 0
    assert "CANCELADO" in (tmp_path / "b" / "LEEME.txt").read_text(encoding="utf-8").upper()
