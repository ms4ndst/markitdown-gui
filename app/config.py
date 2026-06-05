"""Persistent settings stored in a JSON config file.

The file lives under the OS's standard per-user app-config location, which on
Windows is ``%LOCALAPPDATA%\\MarkItDown\\MarkItDown\\config.json``. The path is
exposed via ``config_path()`` so the user can inspect or edit it directly.

If a config from the previous ``Visma\\MarkItDown\\`` location is found and the
new path has no file yet, it is migrated over automatically on first read —
existing API keys and preferences survive the Catppuccin rebrand.

The API key is persisted in **plain text**. This is the simplest behaviour and
matches what every other GUI tool with a "Save API key" checkbox does. If you
are concerned about other users on the same machine reading the file, delete
the key from the config and rely on the ``OPENAI_API_KEY`` environment
variable instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths


CONFIG_FILENAME = "config.json"
FALLBACK_APP_DIR = "MarkItDown"


def config_path() -> Path:
    """Return the full path to the config file. The directory may not exist yet.

    Relies on QApplication.setOrganizationName / setApplicationName having been
    called before this is invoked (see ``app/main.py``). With those set,
    ``AppConfigLocation`` on Windows resolves to
    ``%LOCALAPPDATA%\\MarkItDown\\MarkItDown\\`` — we drop ``config.json`` into
    that directory.
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if base:
        return Path(base) / CONFIG_FILENAME
    return Path.home() / ".config" / FALLBACK_APP_DIR / CONFIG_FILENAME


def _legacy_visma_config_path() -> Path | None:
    """Return the pre-rebrand config path, or None if it can't be resolved."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    return Path(local) / "Visma" / "MarkItDown" / CONFIG_FILENAME


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_config() -> dict[str, Any]:
    """Return the stored config dict; empty dict if the file is missing/invalid.

    Performs a one-time migration from the legacy Visma path if (and only if)
    the new location has no config yet.
    """
    data = _read_json(config_path())
    if data is not None:
        return data

    legacy = _legacy_visma_config_path()
    if legacy is not None:
        legacy_data = _read_json(legacy)
        if legacy_data is not None:
            save_config(legacy_data)
            return legacy_data

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
