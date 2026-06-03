"""Persistent settings stored in a JSON config file.

The file lives under the OS's standard per-user app-config location, which on
Windows is ``%APPDATA%\\VismaMarkItDown\\config.json``. The path is exposed via
``config_path()`` so the user can inspect or edit it directly.

The API key is persisted in **plain text**. This is the simplest behaviour and
matches what every other GUI tool with a "Save API key" checkbox does. If you
are concerned about other users on the same machine reading the file, delete
the key from the config and rely on the ``OPENAI_API_KEY`` environment
variable instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths


CONFIG_FILENAME = "config.json"
FALLBACK_APP_DIR = "VismaMarkItDown"


def config_path() -> Path:
    """Return the full path to the config file. The directory may not exist yet.

    Relies on QApplication.setOrganizationName / setApplicationName having been
    called before this is invoked (see ``app/main.py``). With those set,
    ``AppConfigLocation`` on Windows resolves to
    ``%LOCALAPPDATA%\\Visma\\MarkItDown\\`` — we just drop ``config.json`` into
    that directory.
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if base:
        return Path(base) / CONFIG_FILENAME
    return Path.home() / ".config" / FALLBACK_APP_DIR / CONFIG_FILENAME


def load_config() -> dict[str, Any]:
    """Return the stored config dict; empty dict if the file is missing/invalid."""
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(data: dict[str, Any]) -> None:
    """Atomically write the config to disk, creating the directory if needed."""
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        # Settings persistence is best-effort; never crash the UI over it.
        pass
