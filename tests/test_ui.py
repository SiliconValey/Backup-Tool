"""Prueba de humo de la interfaz (sin mostrar ventanas): python -m pytest"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from backuptool.core.models import FoundItem  # noqa: E402
from backuptool.ui import main_window as mw  # noqa: E402
from backuptool.ui.file_model import FoundItemsModel, FoundItemsProxy  # noqa: E402
from tests.test_core import fake_users, make_chromium  # noqa: E402,F401


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    # Que las pruebas no toquen la configuración real de la app
    monkeypatch.setattr(mw, "APP_NAME", "BackupToolTest")
    yield
    from PySide6.QtCore import QSettings
    QSettings("BackupToolTest", "BackupToolTest").clear()


def wait_until(app, cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def fi(path, size, cat="Imágenes", group=".jpg"):
    return FoundItem(path=path, size=size, mtime=0, category=cat, group=group)


def test_model_checks_and_totals(app):
    m = FoundItemsModel()
    m.add_items([fi("/a/1.jpg", 10), fi("/a/2.jpg", 20), fi("/a/x.mp3", 5, "Audio", ".mp3")])
    m.add_items([fi("/b/3.png", 7, group=".png")])
    assert m.totals() == (4, 42, 4, 42)
    imgs = m.index(0, 0)
    assert imgs.data() == "Imágenes" and m.rowCount(imgs) == 2
    jpg = m.index(0, 0, imgs)
    m.setData(jpg, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert m.totals()[2:] == (2, 12)
    assert imgs.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.PartiallyChecked
    leaf = m.index(1, 0, jpg)
    m.setData(leaf, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert m.totals()[2:] == (3, 32)
    assert [i.path for i in m.checked_items()] == ["/a/2.jpg", "/b/3.png", "/a/x.mp3"]
    m.set_all_checked(False)
    assert m.totals()[2] == 0 and m.checked_items() == []

    p = FoundItemsProxy()
    p.setSourceModel(m)
    p.sort(0, Qt.SortOrder.DescendingOrder)
    assert p.index(0, 0).data() == "Imágenes"      # orden fijo de categorías
    p.set_filter_text("3.PNG")
    assert p.rowCount() == 1
    assert p.rowCount(p.index(0, 0)) == 1


def test_window_scan_and_backup(app, fake_users, tmp_path, monkeypatch):
    make_chromium(fake_users)
    monkeypatch.setattr(mw, "users_root", lambda: str(fake_users))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    win = mw.MainWindow()
    win.settings.clear()
    win.roots_list.clear()
    win._add_root_item(str(fake_users))
    win.cb_drivers.setChecked(False)
    win._start_scan()
    assert wait_until(app, lambda: win._scan_worker is None)
    count, size, checked, _ = win.model.totals()
    assert count == 7 and checked == 7          # 6 archivos + 1 perfil de marcadores
    assert "Búsqueda terminada" in win.status_label.text()

    dest = tmp_path / "usb"
    dest.mkdir()
    win.dest_edit.setText(str(dest))
    win.name_edit.setText("prueba")
    win.cb_wifi.setChecked(False)
    win.cb_programs.setChecked(False)
    win._start_backup()
    assert wait_until(app, lambda: win._backup_worker is None, 20)
    root = dest / "prueba"
    assert (root / "manifiesto.csv").exists()
    assert len([p for p in root.rglob("*") if p.is_file()]) >= 8
    assert "Backup terminado" in win.copy_status.text()
    win.grab().save(str(tmp_path / "shot.png"))
    win.close()


def test_window_filter_switches_model(app, monkeypatch, tmp_path):
    win = mw.MainWindow()
    win.model.add_items([fi("/a/playa.jpg", 10), fi("/a/montaña.jpg", 20),
                         fi("/a/tema.mp3", 5, "Audio", ".mp3")])
    assert win.tree.model() is win.model
    win.filter_edit.setText("playa")
    win._apply_filter()
    assert win.tree.model() is win.proxy
    cat = win.proxy.index(0, 0)
    assert win.proxy.rowCount() == 1 and win.proxy.rowCount(win.proxy.index(0, 0, cat)) == 1
    win.tree.selectAll()
    sel = win._selected_source_indexes()
    assert all(i.model() is win.model for i in sel)
    win.filter_edit.clear()
    win._apply_filter()
    assert win.tree.model() is win.model and win.proxy.sourceModel() is None
    win.model.set_all_checked(False)      # no debe fallar sin proxy conectado
    win.settings.clear()
    win.close()


def test_themes_apply_and_persist(app):
    from backuptool.ui import themes
    win = mw.MainWindow()
    assert not win.windowIcon().isNull()
    for key, _name in themes.THEME_CHOICES:
        win.set_theme(key)
        assert win.theme_actions[key].isChecked()
        assert win.settings.value("theme") == key
    win.set_theme("midnight")
    assert themes.current().key == "midnight"
    assert app.palette().color(app.palette().ColorRole.Window).name() == "#1a2130"
    win2 = mw.MainWindow()            # el tema elegido se recuerda
    assert win2._theme_key == "midnight"
    win2.set_theme(themes.SYSTEM_KEY)
    win.close()
    win2.close()
