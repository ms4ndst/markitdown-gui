"""Entry point for the Catppuccin-themed MarkItDown GUI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import __version__
from .config import load_config
from .main_window import MainWindow
from .theme import ACCENTS, DEFAULT_ACCENT, DEFAULT_FLAVOR, Flavor, apply_catppuccin


def main() -> int:
    from .desktop_entry import DESKTOP_ID, run_cli

    exit_code = run_cli(sys.argv[1:])
    if exit_code is not None:
        return exit_code

    # The Wayland app_id / X11 WM_CLASS that matches the installed desktop
    # entry (markitdown-gui.desktop). Without it the window identifies as
    # "python3", so sway, waybar and launchers can't tie it to its entry
    # and icon. Must be set before the first window is created.
    QApplication.setDesktopFileName(DESKTOP_ID)
    app = QApplication(sys.argv)
    # Org name is part of the QStandardPaths config-dir lookup; keeping it
    # at "MarkItDown" makes the config path neutral. The config module
    # transparently migrates from the legacy %LOCALAPPDATA%\Visma\MarkItDown
    # location on first run.
    app.setApplicationName("MarkItDown")
    app.setOrganizationName("MarkItDown")
    app.setApplicationVersion(__version__)

    # Apply Catppuccin before any widget is created so we don't have to
    # re-polish a tree of widgets that briefly rendered in the default theme.
    cfg = load_config()
    theme = cfg.get("theme") or {}
    flavor = Flavor.from_name(theme.get("flavor"))
    accent = theme.get("accent") if theme.get("accent") in ACCENTS else DEFAULT_ACCENT
    apply_catppuccin(app, flavor or DEFAULT_FLAVOR, accent)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
