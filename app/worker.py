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
        embed_pdf_images: bool = False,
        extract_pdf_images: bool = False,
        strip_pdf_page_numbers: bool = False,
        strip_pdf_headers_footers: bool = False,
        ocr: OcrConfig | None = None,
    ) -> None:
        super().__init__()
        self._items = items
        self._overwrite = overwrite
        self._detect_pdf_tables = detect_pdf_tables
        self._generate_index = generate_index
        self._embed_pdf_images = embed_pdf_images
        self._extract_pdf_images = extract_pdf_images
        self._strip_pdf_page_numbers = strip_pdf_page_numbers
        self._strip_pdf_headers_footers = strip_pdf_headers_footers
        self._ocr = ocr or OcrConfig()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _build_text_markitdown(self) -> MarkItDown:
        """Build the standard MarkItDown used for non-scanned files."""
        md = MarkItDown()
        if self._detect_pdf_tables:
            from .pdf_table_converter import PdfPlumberTableConverter

            # When the user wants images placed at their original position
            # in the PDF, the converter emits a placeholder at every image's
            # on-page y so the post-processor can swap each one for a real
            # link / base64 URI. Without this flag the converter behaves as
            # before and images would still drop to an appendix.
            inline_images = self._embed_pdf_images or self._extract_pdf_images
            md.register_converter(
                PdfPlumberTableConverter(inline_images=inline_images),
                priority=-1.0,
            )
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

        if self._embed_pdf_images:
            self.log.emit(
                "Image handling: embed as base64 "
                "(PDF, DOCX, PPTX, XLSX, EPUB)."
            )
        elif self._extract_pdf_images:
            self.log.emit(
                "Image handling: extract to files in 'images/' subfolder "
                "(PDF, DOCX, PPTX, XLSX, EPUB)."
            )

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
                text_content = result.text_content

                images_md = ""
                if self._embed_pdf_images:
                    # PDF path: PdfPlumberTableConverter (when inline_images
                    # is on) has already dropped MDGUI_IMG placeholders at
                    # each image's on-page position — swap them for real
                    # base64 URIs so images sit where they appeared in the
                    # source. Returns 0 placements for non-PDF or when the
                    # table converter wasn't used; the legacy paths below
                    # then take over.
                    from .pdf_image_extractor import (
                        replace_pdf_image_placeholders_with_base64,
                    )

                    text_content, placed = (
                        replace_pdf_image_placeholders_with_base64(
                            text_content,
                            item.source,
                            log=self.log.emit,
                        )
                    )
                    if placed == 0:
                        # MarkItDown emits *truncated* `data:image/png;base64...`
                        # placeholders for .docx — the URI has no real bytes.
                        # Replace each placeholder with the actual base64
                        # pulled from the source document so the embedded
                        # images are real, not literal "...".
                        if "data:image/" in text_content:
                            from .pdf_image_extractor import (
                                rewrite_truncated_uris_to_base64,
                            )

                            text_content, _ = (
                                rewrite_truncated_uris_to_base64(
                                    text_content,
                                    item.source,
                                    log=self.log.emit,
                                )
                            )
                        else:
                            # Formats markitdown doesn't inline at all (PDF,
                            # most PPTX, all XLSX/EPUB) — extract from source.
                            from .pdf_image_extractor import (
                                extract_document_images_markdown,
                            )

                            images_md = extract_document_images_markdown(
                                item.source, log=self.log.emit
                            )
                elif self._extract_pdf_images:
                    # PDF path: same placeholder swap as embed mode, but
                    # writing PNGs to <md_dir>/images/ and emitting relative
                    # links. One file per unique xref; duplicate references
                    # across pages share it.
                    from .pdf_image_extractor import (
                        replace_pdf_image_placeholders_with_files,
                    )

                    text_content, placed = (
                        replace_pdf_image_placeholders_with_files(
                            text_content,
                            item.source,
                            item.destination,
                            log=self.log.emit,
                        )
                    )
                    if placed == 0:
                        # Rewrite every inline image (full base64 OR
                        # truncated placeholder) to a relative file link,
                        # writing the bytes to <md_dir>/images/. Handles
                        # .docx (truncated placeholders, bytes pulled from
                        # word/media) and any converter that emits real
                        # base64.
                        from .pdf_image_extractor import (
                            rewrite_inline_images_to_files,
                        )

                        text_content, rewritten = (
                            rewrite_inline_images_to_files(
                                text_content,
                                item.source,
                                item.destination,
                                log=self.log.emit,
                            )
                        )
                        # If nothing was inline (PDF without table
                        # detection, most PPTX, XLSX, EPUB), fall back to
                        # pulling images out of the source file directly
                        # and appending the section at the end.
                        if rewritten == 0:
                            from .pdf_image_extractor import (
                                extract_document_images_to_files,
                            )

                            images_md = extract_document_images_to_files(
                                item.source,
                                item.destination,
                                log=self.log.emit,
                            )
                if images_md:
                    text_content = (
                        text_content.rstrip() + "\n\n" + images_md + "\n"
                    )

                # Strip empty / image-only headings that mammoth leaves
                # behind in DOCX output — they lint as MD042 in any
                # markdown linter and break tables of contents.
                from .markdown_cleanup import (
                    apply_lint_fixes,
                    strip_empty_headings,
                    strip_headers_footers,
                    strip_page_numbers,
                )

                text_content, removed_headings = strip_empty_headings(
                    text_content
                )
                if removed_headings:
                    self.log.emit(
                        f"  -> cleaned up {removed_headings} empty / "
                        "image-only heading(s)"
                    )

                # Running-header/footer strip is opt-in, PDF + DOCX. Real
                # Word header/footer XML parts (header1.xml, footer1.xml)
                # are never even in the markdown — mammoth (our .docx
                # converter) only reads word/document.xml and drops them —
                # but a banner typed directly into the body of every page
                # (common in DOCX exported from PDF) repeats identically
                # just like PDF page furniture, so the same frequency-based
                # pass catches it.
                if (
                    self._strip_pdf_headers_footers
                    and item.source.suffix.lower() in (".pdf", ".docx")
                ):
                    text_content, removed_hf = strip_headers_footers(
                        text_content
                    )
                    if removed_hf:
                        self.log.emit(
                            f"  -> removed {removed_hf} running header/footer "
                            "line(s)"
                        )

                # Page-number strip is opt-in and PDF-only — other formats
                # rarely carry raw page numbers as their own paragraphs and
                # we'd risk eating standalone numeric content.
                if (
                    self._strip_pdf_page_numbers
                    and item.source.suffix.lower() == ".pdf"
                ):
                    text_content, removed_pages = strip_page_numbers(
                        text_content
                    )
                    if removed_pages:
                        self.log.emit(
                            f"  -> stripped {removed_pages} page-number line(s)"
                        )

                # Run the markdownlint auto-fix pass over the safely-fixable
                # rules (MD009/MD010/MD012/MD018/MD022/MD026/MD029/MD031/
                # MD032/MD034/MD047). Anything that needs human judgment
                # (MD025/MD041/MD042/MD045 etc.) is left for the downstream
                # linter to flag.
                text_content, lint_fixes = apply_lint_fixes(text_content)
                if lint_fixes:
                    summary = ", ".join(
                        f"{rule}:{n}" for rule, n in sorted(lint_fixes.items())
                    )
                    self.log.emit(f"  -> markdownlint auto-fixed {summary}")

                item.destination.parent.mkdir(parents=True, exist_ok=True)
                item.destination.write_text(text_content, encoding="utf-8")

                success += 1
                self.file_done.emit(str(item.source), str(item.destination))
                char_count = len(text_content)
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
