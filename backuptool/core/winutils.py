"""Utilidades específicas de Windows, con alternativas inofensivas en otros sistemas
(así el núcleo se puede probar en Linux)."""

from __future__ import annotations

import ctypes
import os
import shutil
import string
import subprocess
import sys
from dataclasses import dataclass

IS_WINDOWS = os.name == "nt"

# Atributos de archivo de Windows (st_file_attributes)
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3

CREATE_NO_WINDOW = 0x08000000


@dataclass(slots=True)
class DriveInfo:
    root: str           # "D:\\"
    label: str
    drive_type: int
    filesystem: str
    total: int
    free: int

    @property
    def is_removable(self) -> bool:
        return self.drive_type == DRIVE_REMOVABLE

    def describe(self) -> str:
        kind = "Extraíble" if self.is_removable else "Disco"
        name = f"{self.label} " if self.label else ""
        return (f"{self.root.rstrip(chr(92))} {name}— {kind}, {self.filesystem or '?'}, "
                f"{format_size(self.free)} libres de {format_size(self.total)}")


def format_size(num: float) -> str:
    """Tamaño legible con coma decimal: 1536 -> '1,5 KB'."""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{num} B"


def format_count(n: int) -> str:
    """1234567 -> '1.234.567'."""
    return f"{n:,}".replace(",", ".")


def long_path(path: str) -> str:
    """Prefijo \\\\?\\ para superar el límite de 260 caracteres de Windows."""
    if not IS_WINDOWS:
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def strip_long_path(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def is_admin() -> bool:
    if not IS_WINDOWS:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Relanza el programa pidiendo elevación (UAC). Devuelve True si se lanzó."""
    if not IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):       # ejecutable de PyInstaller
        exe = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        exe = sys.executable
        # pythonw.exe evita que se abra una consola negra junto a la ventana
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if exe.lower().endswith("python.exe") and os.path.isfile(pyw):
            exe = pyw
        params = subprocess.list2cmdline([os.path.abspath(sys.argv[0]), *sys.argv[1:]])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def system_drive() -> str:
    return os.environ.get("SystemDrive", "C:") + "\\"


def users_root() -> str:
    if IS_WINDOWS:
        return os.path.join(system_drive(), "Users")
    return "/home"


def _volume_info(root: str) -> tuple[str, str]:
    """(etiqueta, sistema de archivos) de una unidad."""
    if not IS_WINDOWS:
        return "", ""
    label_buf = ctypes.create_unicode_buffer(261)
    fs_buf = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root), label_buf, 261, None, None, None, fs_buf, 261)
    if not ok:
        return "", ""
    return label_buf.value, fs_buf.value


def filesystem_of(path: str) -> str:
    """Sistema de archivos (NTFS, FAT32, exFAT...) de la unidad que contiene path."""
    if not IS_WINDOWS:
        return ""
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive:
        return ""
    return _volume_info(drive + "\\")[1]


def list_drives() -> list[DriveInfo]:
    """Unidades fijas y extraíbles disponibles."""
    drives: list[DriveInfo] = []
    if not IS_WINDOWS:
        return drives
    kernel32 = ctypes.windll.kernel32
    # Evita el diálogo "No hay disco en la unidad" en lectores vacíos
    old_mode = kernel32.SetErrorMode(1)
    try:
        bitmask = kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if not bitmask & (1 << i):
                continue
            root = f"{letter}:\\"
            dtype = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
            if dtype not in (DRIVE_FIXED, DRIVE_REMOVABLE):
                continue
            try:
                usage = shutil.disk_usage(root)
            except OSError:
                continue   # lector de tarjetas vacío, etc.
            label, fs = _volume_info(root)
            drives.append(DriveInfo(root, label, dtype, fs, usage.total, usage.free))
    finally:
        kernel32.SetErrorMode(old_mode)
    return drives


def decode_console(data: bytes) -> str:
    """Decodifica la salida de comandos de consola (pnputil, netsh)."""
    if not data:
        return ""
    for enc in (("oem",) if IS_WINDOWS else ()) + ("utf-8",):
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("latin-1", errors="replace")


def system_tool(name: str) -> str:
    """Ruta a una herramienta de System32. Con Python de 32 bits en Windows de 64,
    System32 se redirige a SysWOW64 (donde no existe pnputil): se usa Sysnative."""
    if not IS_WINDOWS:
        return name
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for folder in ("Sysnative", "System32"):
        candidate = os.path.join(windir, folder, name)
        if os.path.isfile(candidate):
            return candidate
    return name


def run_command(args: list[str], timeout: int = 600) -> tuple[int, str]:
    """Ejecuta un comando sin abrir ventana de consola y devuelve (código, salida)."""
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    proc = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    out = decode_console(proc.stdout) + decode_console(proc.stderr)
    return proc.returncode, out.strip()


def computer_name() -> str:
    import platform
    return os.environ.get("COMPUTERNAME") or platform.node() or "PC"


def open_in_explorer(path: str, select: bool = True) -> None:
    """Abre el Explorador de Windows mostrando el archivo seleccionado."""
    if IS_WINDOWS:
        if select and os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", path])
        else:
            os.startfile(path if os.path.isdir(path) else os.path.dirname(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
