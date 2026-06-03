"""Entry point for the Visma-branded MarkItDown GUI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MarkItDown")
    app.setOrganizationName("Visma")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
