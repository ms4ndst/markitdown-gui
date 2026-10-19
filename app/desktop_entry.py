"""Install the Linux application-menu entry (``.desktop`` file + icon).

pip only installs commands, so after ``pip install --user .`` the app has no
entry in the application menu (rofi's *Apps*/drun, GNOME, KDE …). Running
``markitdown-gui --install-desktop-entry`` writes one for whichever install
the command belongs to; ``install.sh`` uses the same command, so there is a
single definition of the entry.

Everything goes under ``$XDG_DATA_HOME`` (default ``~/.local/share``):

* ``applications/markitdown-gui.desktop``
* ``icons/hicolor/scalable/apps/markitdown-gui.svg``

The entry's ``StartupWMClass`` and the app's Wayland ``app_id`` are both
:data:`DESKTOP_ID` (see ``app/main.py``), so the running window is matched
to this entry and its icon by sway, waybar, docks and task switchers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

DESKTOP_ID = "markitdown-gui"


def _data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_file_path() -> Path:
    return _data_dir() / "applications" / f"{DESKTOP_ID}.desktop"


def icon_path() -> Path:
    return _data_dir() / "icons" / "hicolor" / "scalable" / "apps" / f"{DESKTOP_ID}.svg"


def launcher_command() -> str:
    """The ``Exec=`` value: the ``markitdown-gui`` launcher that is running
    now (so a venv install points at its venv), else this interpreter."""
    argv0 = Path(sys.argv[0])
    if argv0.name == DESKTOP_ID and argv0.is_file():
        target = str(argv0.absolute())
        return f'"{target}"' if " " in target else target
    python = f'"{sys.executable}"' if " " in sys.executable else sys.executable
    return f"{python} -m app.main"


def desktop_entry(exec_cmd: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=MarkItDown GUI",
        "GenericName=Markdown Converter",
        "Comment=Batch-convert documents and Google Drive folders to Markdown",
        f"Exec={exec_cmd}",
        f"Icon={DESKTOP_ID}",
        "Terminal=false",
        "Categories=Office;",
        "Keywords=markdown;markitdown;convert;pdf;docx;pptx;xlsx;ocr;google;drive;",
        f"StartupWMClass={DESKTOP_ID}",
        "StartupNotify=true",
        "",
    ])


def _refresh_caches(data_dir: Path) -> None:
    """Best effort: some launchers read these caches instead of the files."""
    for cmd in (
        ["update-desktop-database", str(data_dir / "applications")],
        ["gtk-update-icon-cache", "-f", "-t", str(data_dir / "icons" / "hicolor")],
    ):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)


def install(exec_cmd: str | None = None) -> list[Path]:
    """Write the desktop entry and icon; returns the paths written."""
    desktop, icon = desktop_file_path(), icon_path()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(
        resources.files("app").joinpath("resources", f"{DESKTOP_ID}.svg").read_bytes()
    )
    desktop.write_text(desktop_entry(exec_cmd or launcher_command()), encoding="utf-8")
    desktop.chmod(0o644)
    _refresh_caches(_data_dir())
    return [desktop, icon]


def uninstall() -> list[Path]:
    """Remove the desktop entry and icon; returns the paths removed."""
    removed = []
    for path in (desktop_file_path(), icon_path()):
        if path.exists():
            path.unlink()
            removed.append(path)
    _refresh_caches(_data_dir())
    return removed


def run_cli(argv: list[str]) -> int | None:
    """Handle ``--install-desktop-entry`` / ``--uninstall-desktop-entry``.

    Returns an exit code when one of them was given, None otherwise (start
    the GUI).
    """
    if "--install-desktop-entry" in argv:
        for path in install():
            print(f"Wrote {path}")
        print("MarkItDown GUI is now in your application menu.")
        return 0
    if "--uninstall-desktop-entry" in argv:
        removed = uninstall()
        for path in removed:
            print(f"Removed {path}")
        if not removed:
            print("No desktop entry was installed.")
        return 0
    return None
