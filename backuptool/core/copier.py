"""Copia de los elementos seleccionados al destino del backup.

Estructura generada:

    <destino>/<nombre del backup>/
        Imágenes/C/Users/chris/Pictures/...     (o Archivos/C/... si no se agrupa)
        Marcadores/<navegador>/<usuario>/<perfil>/marcadores.html
        Drivers/oemNN/...  + drivers.csv + LEEME.txt
        Sistema/WiFi/*.xml, Sistema/programas_instalados.csv
        manifiesto.csv, errores.log, LEEME.txt

Si se vuelve a ejecutar sobre la misma carpeta, los archivos que ya existen
con igual tamaño y fecha se saltean (útil para retomar un backup cortado).
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Callable

from . import browsers, drivers, extras
from .models import CopyResult, FoundItem, ItemKind
from .winutils import IS_WINDOWS, computer_name, filesystem_of, format_size, long_path

CHUNK = 1024 * 1024
FAT32_MAX = 4 * 1024 ** 3 - 1
MTIME_TOLERANCE = 2.0  # FAT32/exFAT guardan la hora con resolución de 2 s


@dataclass
class CopyOptions:
    dest_root: str
    backup_name: str
    group_by_category: bool = True
    verify: bool = False
    wifi_profiles: bool = True
    wifi_include_keys: bool = False
    programs_list: bool = True


@dataclass
class CopyProgress:
    phase: str
    files_done: int
    files_total: int
    bytes_done: int
    bytes_total: int
    current: str = ""


ProgressCallback = Callable[[CopyProgress], None]
LogCallback = Callable[[str], None]


class CopyCancelled(Exception):
    pass


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    cleaned = _INVALID.sub("_", name).strip(" .")
    return cleaned or "_"


def default_backup_name() -> str:
    return f"Backup_{safe_name(computer_name())}_{time.strftime('%Y-%m-%d_%H%M')}"


def relative_from_absolute(path: str) -> str:
    """C:\\Users\\x\\a.jpg -> C/Users/x/a.jpg ; \\\\srv\\share\\a -> UNC/srv/share/a."""
    path = os.path.normpath(path)
    drive, rest = os.path.splitdrive(path)
    parts: list[str] = []
    if drive.startswith("\\\\") or drive.startswith("//"):
        parts = ["UNC"] + [p for p in re.split(r"[\\/]+", drive) if p]
    elif drive:
        parts = [drive.rstrip(":")]
    parts += [p for p in re.split(r"[\\/]+", rest) if p]
    return os.path.join(*parts) if parts else "_"


def required_space(items: list[FoundItem]) -> int:
    return sum(i.size for i in items if i.kind is not ItemKind.DRIVER)


class BackupRunner:
    def __init__(self, items: list[FoundItem], options: CopyOptions,
                 cancel_event: threading.Event | None = None,
                 progress: ProgressCallback | None = None,
                 log: LogCallback | None = None):
        self.items = items
        self.opt = options
        self.cancel_event = cancel_event or threading.Event()
        self._progress_cb = progress
        self._log_cb = log
        self.result = CopyResult()
        self.backup_dir = os.path.join(options.dest_root, safe_name(options.backup_name))
        self.result.backup_dir = self.backup_dir
        self._manifest: list[dict] = []
        self._last_progress = 0.0
        self._files_total = len(items)
        self._bytes_total = required_space(items)
        self._files_done = 0
        self._bytes_done = 0
        self._fat32 = filesystem_of(options.dest_root).upper() == "FAT32"

    # ------------------------------------------------------------- helpers
    def log(self, msg: str) -> None:
        if self._log_cb:
            self._log_cb(msg)

    def _error(self, msg: str) -> None:
        self.result.errors.append(msg)
        self.log("ERROR: " + msg)

    def _progress(self, phase: str, current: str = "", force: bool = False) -> None:
        if not self._progress_cb:
            return
        now = time.monotonic()
        if force or now - self._last_progress > 0.1:
            self._last_progress = now
            self._progress_cb(CopyProgress(phase, self._files_done, self._files_total,
                                           self._bytes_done, self._bytes_total, current))

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise CopyCancelled()

    def dest_for_file(self, item: FoundItem) -> str:
        top = safe_name(item.category) if self.opt.group_by_category else "Archivos"
        return os.path.join(self.backup_dir, top, relative_from_absolute(item.path))

    # ----------------------------------------------------------------- run
    def run(self) -> CopyResult:
        os.makedirs(long_path(self.backup_dir), exist_ok=True)
        free = shutil.disk_usage(self.opt.dest_root).free
        self.log(f"Destino: {self.backup_dir}")
        self.log(f"A copiar: {len(self.items)} elementos, {format_size(self._bytes_total)} "
                 f"(libre en destino: {format_size(free)})")
        if self._fat32:
            self.log("El destino es FAT32: los archivos de 4 GB o más no se pueden copiar.")
        started = time.time()
        try:
            files = [i for i in self.items if i.kind is ItemKind.FILE]
            marks = [i for i in self.items if i.kind is ItemKind.BOOKMARK]
            drvs = [i for i in self.items if i.kind is ItemKind.DRIVER]
            for item in files:
                self._check_cancel()
                self._copy_file(item)
                self._files_done += 1
            if marks:
                self._backup_bookmarks(marks)
            if drvs:
                self._backup_drivers(drvs)
            if self.opt.wifi_profiles or self.opt.programs_list:
                self._backup_system()
        except CopyCancelled:
            self.result.cancelled = True
            self.log("Backup cancelado por el usuario.")
        finally:
            self._write_reports(started)
        self._progress("Terminado", force=True)
        return self.result

    # -------------------------------------------------------------- archivos
    def _copy_file(self, item: FoundItem) -> None:
        dest = self.dest_for_file(item)
        self._progress("Copiando archivos", item.path)
        row = {"tipo": "archivo", "categoria": item.category, "origen": item.path,
               "destino": os.path.relpath(dest, self.backup_dir), "tamaño": item.size,
               "modificado": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.mtime)),
               "sha256": "", "estado": ""}
        try:
            if self._fat32 and item.size > FAT32_MAX:
                raise OSError("archivo de 4 GB o más: no entra en un destino FAT32")
            if self._already_copied(item, dest):
                row["estado"] = "ya existía"
                self.result.skipped_existing += 1
                self._bytes_done += item.size
            else:
                row["sha256"] = self._copy_with_progress(item.path, dest)
                row["estado"] = "copiado"
                self.result.copied += 1
                self.result.bytes_copied += item.size
        except CopyCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - un archivo no debe frenar el backup
            row["estado"] = f"error: {exc}"
            self.result.failed += 1
            self._error(f"{item.path}: {exc}")
        self._manifest.append(row)

    def _already_copied(self, item: FoundItem, dest: str) -> bool:
        try:
            st = os.stat(long_path(dest))
        except OSError:
            return False
        return st.st_size == item.size and abs(st.st_mtime - item.mtime) <= MTIME_TOLERANCE

    def _copy_with_progress(self, src: str, dest: str) -> str:
        os.makedirs(long_path(os.path.dirname(dest)), exist_ok=True)
        tmp = dest + ".bt_part"
        hasher = hashlib.sha256() if self.opt.verify else None
        try:
            with open(long_path(src), "rb") as fin, open(long_path(tmp), "wb") as fout:
                while True:
                    if self.cancel_event.is_set():
                        raise CopyCancelled()
                    chunk = fin.read(CHUNK)
                    if not chunk:
                        break
                    fout.write(chunk)
                    if hasher:
                        hasher.update(chunk)
                    self._bytes_done += len(chunk)
                    self._progress("Copiando archivos", src)
            shutil.copystat(long_path(src), long_path(tmp))
            os.replace(long_path(tmp), long_path(dest))
        except BaseException:
            try:
                os.remove(long_path(tmp))
            except OSError:
                pass
            raise
        if hasher:
            digest = hasher.hexdigest()
            if _sha256_file(long_path(dest)) != digest:
                raise OSError("la verificación falló: la copia no coincide con el original")
            return digest
        return ""

    # ------------------------------------------------------------ marcadores
    def _backup_bookmarks(self, marks: list[FoundItem]) -> None:
        base = os.path.join(self.backup_dir, "Marcadores")
        for item in marks:
            self._check_cancel()
            self._progress("Guardando marcadores", item.path, force=True)
            dest = os.path.join(base, safe_name(item.extra.get("browser", item.group)),
                                safe_name(item.extra.get("user", "")),
                                safe_name(item.extra.get("profile", "")))
            row = {"tipo": "marcadores", "categoria": item.category, "origen": item.path,
                   "destino": os.path.relpath(dest, self.backup_dir), "tamaño": item.size,
                   "modificado": "", "sha256": "", "estado": ""}
            try:
                _, count = browsers.backup_bookmark(item, dest)
                row["estado"] = f"copiado ({count} marcadores)"
                self.result.bookmarks_saved += 1
                self.log(f"Marcadores de {item.group} ({item.extra.get('user')}): {count}")
            except Exception as exc:  # noqa: BLE001
                row["estado"] = f"error: {exc}"
                self.result.failed += 1
                self._error(f"Marcadores {item.path}: {exc}")
            self._files_done += 1
            self._bytes_done += item.size
            self._manifest.append(row)
        if self.result.bookmarks_saved:
            with open(os.path.join(base, "LEEME.txt"), "w", encoding="utf-8") as fh:
                fh.write("Cada carpeta tiene un archivo marcadores.html que se puede importar\n"
                         "desde cualquier navegador (Chrome/Edge: Marcadores > Importar;\n"
                         "Firefox: Biblioteca > Importar y respaldar > Importar desde HTML).\n"
                         "También se guardó el archivo original del navegador.\n")

    # --------------------------------------------------------------- drivers
    def _backup_drivers(self, drvs: list[FoundItem]) -> None:
        base = os.path.join(self.backup_dir, "Drivers")
        os.makedirs(base, exist_ok=True)
        rows = []
        for item in drvs:
            self._check_cancel()
            inf = item.extra.get("inf", os.path.basename(item.path))
            self._progress("Exportando drivers", inf, force=True)
            ok, out = drivers.export_driver(inf, base)
            status = "exportado" if ok else f"error: {out.splitlines()[-1] if out else 'desconocido'}"
            if ok:
                self.result.drivers_exported += 1
            else:
                self.result.failed += 1
                self._error(f"Driver {inf}: {out or 'sin detalle'}")
            rows.append({"inf": inf, "clase": item.extra.get("class", ""),
                         "fabricante": item.extra.get("provider", ""),
                         "version": item.extra.get("version", ""), "estado": status})
            self._manifest.append({"tipo": "driver", "categoria": item.group, "origen": item.path,
                                   "destino": os.path.join("Drivers", os.path.splitext(inf)[0]),
                                   "tamaño": "", "modificado": "", "sha256": "", "estado": status})
            self._files_done += 1
        with open(os.path.join(base, "drivers.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        with open(os.path.join(base, "LEEME.txt"), "w", encoding="utf-8") as fh:
            fh.write(drivers.RESTORE_README)
        self.log(f"Drivers exportados: {self.result.drivers_exported} de {len(drvs)}")

    # --------------------------------------------------------------- sistema
    def _backup_system(self) -> None:
        base = os.path.join(self.backup_dir, "Sistema")
        if self.opt.wifi_profiles:
            self._check_cancel()
            self._progress("Exportando perfiles Wi-Fi", force=True)
            ok, out = extras.export_wifi_profiles(os.path.join(base, "WiFi"),
                                                  self.opt.wifi_include_keys)
            self.log("Perfiles Wi-Fi exportados." if ok else f"Wi-Fi: {out or 'no se exportó nada'}")
        if self.opt.programs_list:
            self._check_cancel()
            self._progress("Listando programas instalados", force=True)
            try:
                n = extras.write_programs_csv(os.path.join(base, "programas_instalados.csv"))
                self.log(f"Lista de programas instalados: {n}" if n else
                         "Lista de programas: no disponible en este sistema.")
            except Exception as exc:  # noqa: BLE001
                self._error(f"Lista de programas: {exc}")

    # -------------------------------------------------------------- reportes
    def _write_reports(self, started: float) -> None:
        try:
            if self._manifest:
                with open(os.path.join(self.backup_dir, "manifiesto.csv"), "w",
                          newline="", encoding="utf-8-sig") as fh:
                    writer = csv.DictWriter(fh, fieldnames=list(self._manifest[0].keys()),
                                            delimiter=";")
                    writer.writeheader()
                    writer.writerows(self._manifest)
            if self.result.errors:
                with open(os.path.join(self.backup_dir, "errores.log"), "w", encoding="utf-8") as fh:
                    fh.write("\n".join(self.result.errors) + "\n")
            r = self.result
            elapsed = time.time() - started
            with open(os.path.join(self.backup_dir, "LEEME.txt"), "w", encoding="utf-8") as fh:
                fh.write(
                    f"Backup generado por BackupTool\n"
                    f"Equipo: {computer_name()}\n"
                    f"Fecha: {time.strftime('%Y-%m-%d %H:%M')}\n"
                    f"Duración: {int(elapsed // 60)} min {int(elapsed % 60)} s\n"
                    f"{'*** BACKUP INCOMPLETO: fue cancelado ***' if r.cancelled else ''}\n\n"
                    f"Archivos copiados: {r.copied} ({format_size(r.bytes_copied)})\n"
                    f"Ya existían: {r.skipped_existing}\n"
                    f"Marcadores: {r.bookmarks_saved} perfiles\n"
                    f"Drivers: {r.drivers_exported}\n"
                    f"Errores: {r.failed}\n\n"
                    f"manifiesto.csv tiene el detalle de cada elemento (origen y destino).\n"
                )
        except OSError as exc:
            self.log(f"No se pudieron escribir los reportes: {exc}")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = ["BackupRunner", "CopyOptions", "CopyProgress", "default_backup_name",
           "relative_from_absolute", "required_space", "IS_WINDOWS"]
