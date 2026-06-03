"""Background detection of scanned (image-only) PDFs.

A PDF is judged "scanned" when at least 80% of its pages contain images but
extract fewer than 50 characters of text. Detection opens every page with
pdfplumber so it's not cheap — runs on a small thread pool to keep the UI
responsive.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path

from PySide6.QtCore import QObject, Signal


def is_scanned_pdf(
    path: str,
    text_threshold: int = 50,
    scanned_ratio: float = 0.8,
) -> bool:
    try:
        import pdfplumber
    except ImportError:
        return False

    try:
        with pdfplumber.open(path) as pdf:
            pages = pdf.pages
            if not pages:
                return False
            scanned = 0
            for page in pages:
                try:
                    text = (page.extract_text() or "").strip()
                    has_image = bool(page.images)
                finally:
                    page.close()
                if len(text) < text_threshold and has_image:
                    scanned += 1
            return scanned / len(pages) >= scanned_ratio
    except Exception:
        return False


class ScanDetector(QObject):
    """Submits PDF paths for scan detection; emits results back on the main thread."""

    result_ready = Signal(str, bool)  # path, is_scanned

    def __init__(self, max_workers: int = 2) -> None:
        super().__init__()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="scan-detect"
        )

    def submit(self, path: str) -> None:
        if not path.lower().endswith(".pdf"):
            return
        if not Path(path).is_file():
            return
        future = self._executor.submit(is_scanned_pdf, path)
        future.add_done_callback(lambda f, p=path: self._on_done(p, f))

    def _on_done(self, path: str, future: Future) -> None:
        try:
            result = bool(future.result())
        except Exception:
            result = False
        # Qt auto-marshals signal emissions to the receiver's thread.
        self.result_ready.emit(path, result)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
