"""Application bootstrap module."""

import sys

from PyQt6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def run() -> int:
    """Create and run QApplication."""
    app = QApplication(sys.argv)
    app.setApplicationName("StoneReader")

    window = MainWindow()
    window.show()

    return app.exec()
