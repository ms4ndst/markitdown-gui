"""Tests for ``markitdown-gui --install-desktop-entry`` (app/desktop_entry.py)."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from app import desktop_entry


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Keep the cache refresh off the real system tools' side effects.
    monkeypatch.setattr(desktop_entry, "_refresh_caches", lambda _d: None)
    return tmp_path


def test_install_writes_entry_and_icon(data_home, monkeypatch):
    launcher = data_home / "venv" / "bin" / "markitdown-gui"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(launcher), "--install-desktop-entry"])

    assert desktop_entry.run_cli(sys.argv[1:]) == 0

    entry = (data_home / "applications" / "markitdown-gui.desktop").read_text()
    assert f"Exec={launcher}\n" in entry
    assert "Icon=markitdown-gui\n" in entry
    # Must match the app_id set in app/main.py.
    assert "StartupWMClass=markitdown-gui\n" in entry
    assert "%f" not in entry  # the app takes no file arguments
    icon = data_home / "icons/hicolor/scalable/apps/markitdown-gui.svg"
    assert icon.read_bytes().startswith(b"<svg") or b"<svg" in icon.read_bytes()[:200]


def test_exec_falls_back_to_module_when_not_run_from_launcher(data_home, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["-c"])
    entry = desktop_entry.desktop_entry(desktop_entry.launcher_command())
    assert f"Exec={sys.executable} -m app.main\n" in entry


@pytest.mark.skipif(not shutil.which("desktop-file-validate"),
                    reason="desktop-file-validate not installed")
def test_entry_passes_desktop_file_validate(data_home):
    desktop_entry.install("/opt/markitdown-gui/bin/markitdown-gui")
    result = subprocess.run(
        ["desktop-file-validate", str(desktop_entry.desktop_file_path())],
        capture_output=True, text=True,
    )
    assert result.returncode == 0 and not result.stdout.strip(), result.stdout


def test_uninstall_removes_both(data_home):
    desktop_entry.install("/x/markitdown-gui")
    assert desktop_entry.run_cli(["--uninstall-desktop-entry"]) == 0
    assert not desktop_entry.desktop_file_path().exists()
    assert not desktop_entry.icon_path().exists()


def test_other_arguments_start_the_gui():
    assert desktop_entry.run_cli([]) is None
    assert desktop_entry.run_cli(["--something"]) is None
