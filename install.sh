#!/usr/bin/env bash
# Installs markitdown-gui for the current user: a dedicated venv under
# $XDG_DATA_HOME, a `markitdown-gui` launcher on $XDG_BIN_HOME, and a
# desktop entry + icon so it shows up in the application menu.
#
# Run ./uninstall.sh to remove everything this script creates.
set -euo pipefail

APP_NAME="markitdown-gui"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
INSTALL_DIR="$DATA_DIR/$APP_NAME"
VENV_DIR="$INSTALL_DIR/venv"
ICON_DIR="$DATA_DIR/icons/hicolor/scalable/apps"
DESKTOP_DIR="$DATA_DIR/applications"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but was not found on PATH." >&2
    exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Error: Python 3.10+ is required (found $(python3 --version 2>&1))." >&2
    exit 1
fi

echo "Installing $APP_NAME into $INSTALL_DIR ..."

if [ ! -d "$VENV_DIR" ]; then
    if ! python3 -m venv "$VENV_DIR"; then
        echo "Error: failed to create a virtualenv. On Debian/Ubuntu you may need:" >&2
        echo "  sudo apt install python3-venv" >&2
        exit 1
    fi
fi

"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install "$REPO_DIR"

mkdir -p "$BIN_DIR" "$ICON_DIR" "$DESKTOP_DIR"

install -m644 "$REPO_DIR/packaging/linux/markitdown-gui.svg" "$ICON_DIR/markitdown-gui.svg"

sed "s|@EXEC@|$VENV_DIR/bin/markitdown-gui|" \
    "$REPO_DIR/packaging/linux/markitdown-gui.desktop.in" > "$DESKTOP_DIR/markitdown-gui.desktop"
chmod 644 "$DESKTOP_DIR/markitdown-gui.desktop"

ln -sf "$VENV_DIR/bin/markitdown-gui" "$BIN_DIR/markitdown-gui"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "$DATA_DIR/icons/hicolor" >/dev/null 2>&1 || true
fi

echo
echo "Installed. Launch MarkItDown GUI from your application menu, or run:"
echo "  $BIN_DIR/markitdown-gui"

case ":${PATH:-}:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo
        echo "Note: $BIN_DIR is not on your PATH, so the 'markitdown-gui' command"
        echo "won't work from a terminal until you add it, e.g. in ~/.bashrc:"
        echo "  export PATH=\"$BIN_DIR:\$PATH\""
        ;;
esac
