"""Punto de entrada de BackupTool.

    python main.py
"""

import sys

from PySide6.QtWidgets import QApplication

from backuptool import APP_NAME
from backuptool.core.winutils import IS_WINDOWS
from backuptool.ui.main_window import MainWindow
from backuptool.ui.themes import app_icon


def main() -> int:
    if IS_WINDOWS:
        # Ícono propio en la barra de tareas (y no el de python.exe)
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ISFT179.BackupTool")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
