"""Drivers de terceros instalados (los que no vienen con Windows).

Windows guarda cada driver de terceros como ``C:\\Windows\\INF\\oemNN.inf``.
Listarlos no requiere permisos; exportarlos con ``pnputil`` sí requiere
ejecutar como administrador.

Para restaurar en una instalación nueva:
    pnputil /add-driver "<carpeta>\\*.inf" /subdirs /install
"""

from __future__ import annotations

import configparser
import glob
import os
import re

from .categories import DRIVERS_LABEL
from .models import FoundItem, ItemKind
from .winutils import IS_WINDOWS, run_command, system_tool

# Nombres en español para las clases de dispositivo más comunes
CLASS_NAMES = {
    "display": "Video / gráficos",
    "media": "Sonido",
    "net": "Red",
    "bluetooth": "Bluetooth",
    "usb": "USB",
    "hidclass": "Teclado / mouse / HID",
    "keyboard": "Teclado / mouse / HID",
    "mouse": "Teclado / mouse / HID",
    "system": "Dispositivos del sistema",
    "printer": "Impresoras",
    "printqueue": "Impresoras",
    "image": "Cámaras y escáneres",
    "camera": "Cámaras y escáneres",
    "scsiadapter": "Almacenamiento",
    "hdc": "Almacenamiento",
    "diskdrive": "Almacenamiento",
    "softwarecomponent": "Componentes de software",
    "extension": "Extensiones",
    "firmware": "Firmware",
    "biometric": "Biométricos",
    "monitor": "Monitores",
    "ports": "Puertos (COM y LPT)",
    "battery": "Batería",
    "sensor": "Sensores",
    "securitydevices": "Seguridad (TPM)",
}


def inf_dir() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "INF")


def _read_inf_text(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def parse_inf(path: str) -> dict:
    """Lee Class, Provider, DriverVer de la sección [Version] y resuelve %strings%."""
    text = _read_inf_text(path)
    parser = configparser.RawConfigParser(strict=False, allow_no_value=True,
                                          comment_prefixes=(";",), inline_comment_prefixes=(";",),
                                          delimiters=("=",), interpolation=None)
    parser.optionxform = str.lower  # type: ignore[assignment]
    try:
        parser.read_string(text)
    except configparser.Error:
        # INF raros: buscar a mano lo indispensable
        info = {}
        for key in ("class", "provider", "driverver"):
            m = re.search(rf"^\s*{key}\s*=\s*(.+)$", text, re.I | re.M)
            if m:
                info[key] = m.group(1).strip().strip('"')
        return info

    def section(name: str) -> dict:
        for s in parser.sections():
            if s.lower() == name:
                return dict(parser.items(s))
        return {}

    version = section("version")
    strings = {k.lower(): (v or "").strip().strip('"') for k, v in section("strings").items()}

    def resolve(value: str | None) -> str:
        if not value:
            return ""
        value = value.strip().strip('"')
        m = re.fullmatch(r"%([^%]+)%", value)
        if m:
            return strings.get(m.group(1).lower(), value)
        return value

    return {
        "class": resolve(version.get("class")),
        "provider": resolve(version.get("provider")),
        "driverver": resolve(version.get("driverver")),
    }


def list_third_party_drivers(directory: str | None = None) -> list[FoundItem]:
    directory = directory or inf_dir()
    items: list[FoundItem] = []
    for path in sorted(glob.glob(os.path.join(directory, "oem*.inf")),
                       key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
        try:
            info = parse_inf(path)
            st = os.stat(path)
        except OSError:
            continue
        cls = info.get("class", "") or "Otros"
        group = CLASS_NAMES.get(cls.lower(), cls)
        provider = info.get("provider", "") or "Fabricante desconocido"
        version = info.get("driverver", "")
        version = version.split(",")[-1].strip() if version else ""
        name = os.path.basename(path)
        label = f"{provider} — {name}" + (f" (v{version})" if version else "")
        items.append(FoundItem(
            path=path, size=st.st_size, mtime=st.st_mtime, category=DRIVERS_LABEL,
            group=group, kind=ItemKind.DRIVER, display_name=label,
            extra={"inf": name, "class": cls, "provider": provider, "version": version},
        ))
    return items


def export_driver(inf_name: str, dest_dir: str) -> tuple[bool, str]:
    """Exporta un driver (ej. 'oem12.inf') con pnputil. Requiere administrador."""
    if not IS_WINDOWS:
        return False, "Sólo disponible en Windows"
    target = os.path.join(dest_dir, os.path.splitext(inf_name)[0])
    os.makedirs(target, exist_ok=True)
    try:
        code, out = run_command([system_tool("pnputil.exe"), "/export-driver", inf_name, target], timeout=300)
    except (OSError, TimeoutError) as exc:
        return False, str(exc)
    return code == 0, out


RESTORE_README = """\
DRIVERS EXPORTADOS POR BACKUPTOOL
=================================

Cada carpeta (oemNN) contiene un paquete de driver de terceros tal como estaba
instalado en el equipo original. En drivers.csv está el detalle de cada uno.

Para reinstalarlos todos en un Windows nuevo, abrir una consola como
administrador en esta carpeta y ejecutar:

    pnputil /add-driver "*.inf" /subdirs /install

También se puede instalar uno solo desde el Administrador de dispositivos:
clic derecho en el dispositivo > Actualizar controlador > Buscar en mi equipo
> elegir la carpeta correspondiente.
"""
