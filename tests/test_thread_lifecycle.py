"""Closing the window must never abort with "QThread: Destroyed while thread
is still running" — neither right after a conversion finishes nor while one
is still running.

Each scenario runs in a subprocess: the failure is a Qt ``qFatal`` that
aborts the whole process, which would take pytest down with it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)
app.setOrganizationName("MarkItDownTest")
app.setApplicationName("MarkItDownTest")
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
from app.main_window import MainWindow

root, mode = Path(sys.argv[1]), sys.argv[2]
w = MainWindow()
w.input_dir.setText(str(root / "in"))
w.output_dir.setText(str(root / "out"))
w.overwrite_check.setChecked(True)
w._add_path(root / "in" / "a.md")
w._start_conversion()
if mode == "during":
    QTimer.singleShot(0, lambda: (w.close(), app.quit()))
else:
    # Close the moment the GUI has handled `finished` — the thread is then
    # typically still winding down.
    poll = QTimer()
    poll.setInterval(1)
    def check():
        if w._worker is None:
            poll.stop()
            w.close()
            app.quit()
    poll.timeout.connect(check)
    poll.start()
app.exec()
print("exited cleanly", flush=True)
"""


@pytest.mark.parametrize("mode", ["after", "during"])
def test_close_does_not_abort(tmp_path, mode):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a.md").write_text("# Hi\n\nText.\n", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "QT_QPA_PLATFORM": "offscreen",
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(tmp_path), mode],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
    )
    assert "Destroyed while thread" not in proc.stderr
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "exited cleanly" in proc.stdout
