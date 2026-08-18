#!/usr/bin/env bash
# Removes everything ./install.sh created: the venv, the launcher symlink,
# the desktop entry, and the icon. User config/API keys are left in place
# (see the "Configuration" section of README.md).
set -euo pipefail

APP_NAME="markitdown-gui"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"

rm -rf "$DATA_DIR/$APP_NAME"
rm -f "$BIN_DIR/markitdown-gui"
rm -f "$DATA_DIR/applications/markitdown-gui.desktop"
rm -f "$DATA_DIR/icons/hicolor/scalable/apps/markitdown-gui.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DATA_DIR/applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "$DATA_DIR/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "markitdown-gui uninstalled."
echo "Config/API keys (if any) were left under ~/.config/MarkItDown/."
