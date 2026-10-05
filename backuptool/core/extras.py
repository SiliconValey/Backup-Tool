"""Datos extra del sistema: perfiles Wi-Fi y lista de programas instalados."""

from __future__ import annotations

import csv
import os

from .winutils import IS_WINDOWS, run_command, system_tool

UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def export_wifi_profiles(dest_dir: str, include_keys: bool = False) -> tuple[bool, str]:
    """Exporta los perfiles Wi-Fi como XML (importables con netsh wlan add profile).

    Con include_keys=True las contraseñas quedan en texto plano dentro del XML
    (requiere administrador).
    """
    if not IS_WINDOWS:
        return False, "Sólo disponible en Windows"
    os.makedirs(dest_dir, exist_ok=True)
    args = [system_tool("netsh.exe"), "wlan", "export", "profile", f"folder={dest_dir}"]
    if include_keys:
        args.append("key=clear")
    try:
        code, out = run_command(args, timeout=120)
    except OSError as exc:
        return False, str(exc)
    exported = [f for f in os.listdir(dest_dir) if f.lower().endswith(".xml")]
    if exported:
        with open(os.path.join(dest_dir, "LEEME.txt"), "w", encoding="utf-8") as fh:
            fh.write(
                "Perfiles Wi-Fi exportados.\n\n"
                "Para restaurar uno, en una consola ejecutar:\n"
                '    netsh wlan add profile filename="<archivo>.xml" user=all\n\n'
                + ("ATENCIÓN: estos archivos contienen las contraseñas en texto plano.\n"
                   if include_keys else
                   "Las contraseñas no se incluyeron: habrá que escribirlas al conectarse.\n")
            )
    return code == 0 and bool(exported), out


def list_installed_programs() -> list[dict]:
    """Programas instalados según el registro (64 bits, 32 bits y del usuario)."""
    if not IS_WINDOWS:
        return []
    import winreg

    sources = [
        (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, winreg.KEY_WOW64_64KEY, "Equipo (64 bits)"),
        (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, winreg.KEY_WOW64_32KEY, "Equipo (32 bits)"),
        (winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, "Usuario actual"),
    ]
    programs: dict[tuple[str, str], dict] = {}
    for hive, path, flag, scope in sources:
        try:
            root = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | flag)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    sub = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, sub) as key:
                        values = {}
                        for j in range(winreg.QueryInfoKey(key)[1]):
                            n, v, _ = winreg.EnumValue(key, j)
                            values[n] = v
                except OSError:
                    continue
                name = str(values.get("DisplayName", "")).strip()
                if not name or values.get("SystemComponent") == 1 or values.get("ParentKeyName"):
                    continue
                version = str(values.get("DisplayVersion", "") or "")
                k = (name.casefold(), version)
                if k in programs:
                    continue
                date = str(values.get("InstallDate", "") or "")
                if len(date) == 8 and date.isdigit():
                    date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
                programs[k] = {
                    "Nombre": name,
                    "Versión": version,
                    "Fabricante": str(values.get("Publisher", "") or ""),
                    "Instalado": date,
                    "Ámbito": scope,
                }
    return sorted(programs.values(), key=lambda p: p["Nombre"].casefold())


def write_programs_csv(path: str) -> int:
    programs = list_installed_programs()
    if not programs:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # utf-8-sig y ';' para que Excel en español lo abra con columnas correctas
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(programs[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(programs)
    return len(programs)
