"""Tareas en segundo plano (QThread) para que la ventana no se congele."""

from __future__ import annotations

import threading
import time
import traceback

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core import browsers, drivers
from ..core.copier import BackupRunner, CopyOptions
from ..core.models import CopyResult, FoundItem, ScanStats
from ..core.scanner import ScanOptions, Scanner

BATCH_SIZE = 500
BATCH_SECONDS = 0.3


class ScanWorker(QObject):
    batch = Signal(object)              # list[FoundItem]
    progress = Signal(object, str)      # ScanStats, carpeta actual
    status = Signal(str)
    finished = Signal(object)           # ScanStats
    failed = Signal(str)

    def __init__(self, options: ScanOptions, include_bookmarks: bool, include_drivers: bool,
                 users_root: str):
        super().__init__()
        self.options = options
        self.include_bookmarks = include_bookmarks
        self.include_drivers = include_drivers
        self.users_root = users_root
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            extra = 0
            if self.include_bookmarks and not self.cancel_event.is_set():
                self.status.emit("Buscando marcadores de navegadores…")
                found = browsers.find_bookmark_sources(self.users_root)
                extra += len(found)
                self.batch.emit(found)
            if self.include_drivers and not self.cancel_event.is_set():
                self.status.emit("Listando drivers de terceros…")
                found = drivers.list_third_party_drivers()
                extra += len(found)
                self.batch.emit(found)

            scanner = Scanner(self.options, self.cancel_event,
                              progress=lambda st, cur: self.progress.emit(st, cur))
            buf: list[FoundItem] = []
            last = time.monotonic()
            if self.options.roots:
                self.status.emit("Recorriendo carpetas…")
            for item in scanner.scan():
                buf.append(item)
                now = time.monotonic()
                if len(buf) >= BATCH_SIZE or now - last >= BATCH_SECONDS:
                    self.batch.emit(buf)
                    buf = []
                    last = now
            if buf:
                self.batch.emit(buf)
            stats = scanner.stats
            stats.items_found += extra
            self.finished.emit(stats)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc())
            self.finished.emit(ScanStats(cancelled=True))


class BackupWorker(QObject):
    progress = Signal(object)    # CopyProgress
    log = Signal(str)
    finished = Signal(object)    # CopyResult

    def __init__(self, items: list[FoundItem], options: CopyOptions):
        super().__init__()
        self.items = items
        self.options = options
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            runner = BackupRunner(self.items, self.options, self.cancel_event,
                                  progress=self.progress.emit, log=self.log.emit)
            result = runner.run()
        except Exception as exc:  # noqa: BLE001
            self.log.emit("ERROR inesperado:\n" + traceback.format_exc())
            result = CopyResult(failed=1, errors=[str(exc)])
        self.finished.emit(result)


def start_in_thread(worker: QObject, owner: QObject) -> QThread:
    """Mueve el worker a un hilo nuevo y lo arranca. El hilo se libera solo al terminar."""
    thread = QThread(owner)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)          # type: ignore[attr-defined]
    worker.finished.connect(thread.quit)        # type: ignore[attr-defined]
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
