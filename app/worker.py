"""Background worker that converts files to Markdown using MarkItDown."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from markitdown import MarkItDown


@dataclass
class ConversionItem:
    source: Path
    destination: Path
    is_scanned: bool = False  # set by the GUI's scan detector for PDFs


@dataclass
class OcrConfig:
    """Configuration for the optional LLM-vision OCR plugin."""
    enabled: bool = False
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""  # blank → OpenAI default; set for Azure / LM Studio / Ollama


class ConversionWorker(QObject):
    progress = Signal(int, int, str)         # done_count, total, current_filename
    file_done = Signal(str, str)             # source_path, destination_path
    file_failed = Signal(str, str)           # source_path, error_message
    log = Signal(str)                        # log line
    finished = Signal(int, int)              # success_count, failure_count

    def __init__(
        self,
        items: list[ConversionItem],
        overwrite: bool,
        detect_pdf_tables: bool = False,
        generate_index: bool = False,
        ocr: OcrConfig | None = None,
    ) -> None:
        super().__init__()
        self._items = items
        self._overwrite = overwrite
        self._detect_pdf_tables = detect_pdf_tables
        self._generate_index = generate_index
        self._ocr = ocr or OcrConfig()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _build_text_markitdown(self) -> MarkItDown:
        """Build the standard MarkItDown used for non-scanned files."""
        md = MarkItDown()
        if self._detect_pdf_tables:
            from .pdf_table_converter import PdfPlumberTableConverter

            md.register_converter(PdfPlumberTableConverter(), priority=-1.0)
        return md

    def _build_ocr_markitdown(self) -> MarkItDown:
        """Build a MarkItDown with the LLM-vision OCR plugin registered."""
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OCR requires the 'openai' package. Install with "
                "`pip install openai markitdown-ocr`."
            ) from exc

        client_kwargs = {}
        if self._ocr.api_key:
            client_kwargs["api_key"] = self._ocr.api_key
        if self._ocr.base_url:
            client_kwargs["base_url"] = self._ocr.base_url
            # Local endpoints (LM Studio, Ollama) ignore the key but the
            # OpenAI client still requires the field to be set.
            client_kwargs.setdefault("api_key", "not-needed")
        client = OpenAI(**client_kwargs)
        md = MarkItDown(
            enable_plugins=True,
            llm_client=client,
            llm_model=self._ocr.model,
        )
        self._verify_ocr_plugin_loaded(md)
        return md

    def _build_converters(self) -> tuple[MarkItDown, MarkItDown | None]:
        """Return ``(text_md, ocr_md)``. ``ocr_md`` is ``None`` when OCR is off
        or when no items in the queue are scanned PDFs."""
        text_md = self._build_text_markitdown()

        if not self._ocr.enabled:
            return text_md, None

        needs_ocr = any(item.is_scanned for item in self._items)
        if not needs_ocr:
            self.log.emit(
                "OCR enabled but no scanned PDFs in the queue — using the "
                "fast text converter for every file."
            )
            return text_md, None

        ocr_md = self._build_ocr_markitdown()
        self.log.emit(
            f"OCR enabled for scanned PDFs — model={self._ocr.model}"
            + (f", endpoint={self._ocr.base_url}" if self._ocr.base_url else "")
        )
        return text_md, ocr_md

    def _pick_converter(
        self,
        item: ConversionItem,
        text_md: MarkItDown,
        ocr_md: MarkItDown | None,
    ) -> tuple[MarkItDown, str]:
        if ocr_md is not None and item.is_scanned:
            return ocr_md, "OCR"
        return text_md, "text"

    def _verify_ocr_plugin_loaded(self, md: MarkItDown) -> None:
        """Fail loudly if the OCR plugin isn't installed / discoverable."""
        names = [type(c.converter).__name__ for c in md._converters]
        if not any("OCR" in n for n in names):
            raise RuntimeError(
                "OCR was requested but markitdown-ocr is not installed or its "
                "entry-point isn't discoverable. Install it with "
                "`pip install markitdown-ocr`. Registered converters: "
                + ", ".join(sorted(set(names)))
            )

    def run(self) -> None:
        try:
            text_md, ocr_md = self._build_converters()
        except Exception as exc:
            self.log.emit("=" * 60)
            self.log.emit(f"! Failed to initialise converter: {exc}")
            self.log.emit("! No files were converted.")
            self.log.emit("=" * 60)
            self.finished.emit(0, len(self._items))
            return

        # Pipe per-page OCR progress (emitted from inside the markitdown-ocr
        # plugin) into our log so the user sees what's happening during long
        # scanned-PDF conversions.
        progress_installed = False
        if ocr_md is not None:
            try:
                from markitdown_ocr import _pdf_converter_with_ocr as _ocr_mod
                _ocr_mod.set_progress_callback(self.log.emit)
                progress_installed = True
            except Exception:
                pass

        total = len(self._items)
        success = 0
        failure = 0

        for index, item in enumerate(self._items):
            if self._cancelled:
                self.log.emit("Conversion cancelled by user.")
                break

            md, route = self._pick_converter(item, text_md, ocr_md)
            self.progress.emit(index, total, item.source.name)
            self.log.emit(f"Converting [{route}]: {item.source}")

            try:
                if item.destination.exists() and not self._overwrite:
                    raise FileExistsError(
                        f"{item.destination.name} already exists (overwrite disabled)"
                    )

                result = md.convert(str(item.source))
                item.destination.parent.mkdir(parents=True, exist_ok=True)
                item.destination.write_text(
                    result.text_content, encoding="utf-8"
                )

                success += 1
                self.file_done.emit(str(item.source), str(item.destination))
                char_count = len(result.text_content)
                self.log.emit(f"  -> {item.destination} ({char_count} chars)")
                if char_count < 50:
                    self.log.emit(
                        "  ! Warning: output is nearly empty. If this is a "
                        "scanned PDF, enable 'OCR images in PDFs' and provide "
                        "a vision model + API key."
                    )

                if self._generate_index:
                    from .indexer import build_index, should_index

                    if should_index(result.text_content):
                        index_path = item.destination.with_suffix(".index.md")
                        index_path.write_text(
                            build_index(result.text_content, item.source.name),
                            encoding="utf-8",
                        )
                        self.log.emit(f"  -> {index_path}")
            except Exception as exc:  # noqa: BLE001 - surface every error to the user
                failure += 1
                msg = f"{type(exc).__name__}: {exc}"
                self.file_failed.emit(str(item.source), msg)
                self.log.emit(f"  ! Failed: {msg}")

        if progress_installed:
            try:
                _ocr_mod.set_progress_callback(None)
            except Exception:
                pass

        self.progress.emit(total, total, "")
        self.finished.emit(success, failure)


def run_in_thread(worker: ConversionWorker) -> QThread:
    """Move a worker onto a fresh QThread and start it. Returns the thread."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
