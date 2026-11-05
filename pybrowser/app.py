from __future__ import annotations

import argparse
import signal
import sys
from multiprocessing import freeze_support
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import apply_dark_theme


def install_console_interrupt(app: QApplication) -> QTimer:
    """Let Ctrl+C close all windows through their normal safety prompts."""
    def interrupt_handler(_signum, _frame):
        QTimer.singleShot(0, app.closeAllWindows)

    signal.signal(signal.SIGINT, interrupt_handler)
    # Returning to the Python interpreter periodically lets SIGINT run while
    # Qt owns the primary event loop, including on Windows console launches.
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
    return timer


def main(argv=None):
    # Required for ProcessPoolExecutor child startup on Windows and frozen apps.
    freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", type=Path)
    args = parser.parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("PyBrowser")
    app.setQuitOnLastWindowClosed(True)
    apply_dark_theme(app)
    interrupt_timer = install_console_interrupt(app)
    app._console_interrupt_timer = interrupt_timer
    window = MainWindow(args.file)
    window.show()
    return app.exec()
