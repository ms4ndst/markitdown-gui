"""Catppuccin-themed MarkItDown GUI main window."""

from __future__ import annotations

import os
import threading
from pathlib import Path, PurePosixPath

from PySide6.QtCore import Qt, QByteArray, QRect, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QSpacerItem,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .config import config_path, load_config, save_config
from .flow_layout import FlowLayout, group
from .gdrive import (
    DriveEntry,
    DriveListWorker,
    SignInWorker,
    parse_folder_id,
    sign_out,
    token_path,
)
from .llm_discovery import (
    LocalLLMDiscovery,
    LocalServer,
    PROVIDER_PRESETS,
    is_vision_model,
)
from .scan_detector import ScanDetector
from .theme import (
    ACCENTS,
    Flavor,
    PALETTES,
    apply_catppuccin,
    catppuccin_cat_svg,
    current_accent_hex,
    current_palette,
    refresh_widgets,
)
from .worker import (
    ConversionItem,
    ConversionWorker,
    OcrConfig,
    run_in_thread,
    stop_threads,
)


SCANNED_ROLE = Qt.ItemDataRole.UserRole + 1
# DriveEntry.to_dict() for queue items that live in Google Drive.
DRIVE_ROLE = Qt.ItemDataRole.UserRole + 2


_HELLO_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAMgAAABQCAIAAADTD63nAAAF5UlEQVR4nO3dX0hTbRwH8LP5sunZ0JpiVlArE7vQUAykzKgb+0u1JmYyL0ZgpGDdKBW1i/4LwXajFyH9YxpBNCJFikQohCal4W4MxaQwxH/o9OiSuRO8z/seJNsa8/zkPe/5fq5+cn7PeYR9d56dZwfViKLIAchNK/sZARAsoIIrFpBAsIAEggUkECwggWABCQQLSCBYQALBAhIIFpBAsIAEggUkECwggWABCQQLSCBYQALBAhIIFpBAsIAEggUkECxQbLB27typ+Vf0o4aGhqRRxcXFsv9WLpdLOv/4+HiUhyBKuGIBCQQLSCBYQALBAhIIFpBAsIAEggUk/g/BWlhYcLvdZWVlGRkZSUlJCQkJmzZtKioqunv37ujoKN28MzMzDQ0NFovFbDYbjUae581m86FDh1wuF3a/OJFeXl6e9GJEP+rLly/SKKvVGq7t+fPnZrM53GtvMBiuXbu2uLi4fKDT6ZTaxsbGojzEhEIhl8uVlJQUbl6j0RhuXpVQ9hXrxo0bVqt1aGgoXIMgCA6H49ixY4FAQK5Jg8Gg1Wq9cOHC9PR0uJ7Z2VmHw3H06FFBEDhVUnCwHjx4cPXqVfYXCQ0GQ01Njdfr9fv9gUBgYGCgoaFh69atrLO1tbWqqkqueSsqKjweD6t1Ol11dbXX652enhYEoaen59KlSzzPs6NtbW12u51Tp1VeCmOzfCn8+vVrQkICO5qenj4wMLB8XkEQLBaLdJK2traVL4Vv3ryRDqWlpXV3dy+ft6+vb+nq/PDhQ1F9lHrFcjqd8/PzHMfp9frW1tb09PTlPTzPP3nyJCMjg/1469atlc975coVVsTFxT179iw3N3d5T2Zm5suXL+Pj49mPN2/eXFxc5FRGkcESRfHRo0esPnXqVGZmZrhOvV5/7tw5Vr97925kZGQl837//v39+/estlgsBQUF4TqzsrLOnDnD6v7+/q6uLk5l/lrl+To6OqLsHBkZOX369G8P+Xy+yclJVu/fvz/yefbs2SPVb9++LSkp4WLV3t4u1TabLXJzeXl5fX09qzs6Onbt2sWpyWoHa9++fVF2RrjX6+npkWr736I85+DgILcCfX19Up2fnx+5OTc3V6fTLSws/DJQJRS5FMa8/TgxMSHLvFqtdt26dZGbdTqdyWSSZV4lUmSwpqamYhvIPu/HzO/3s4Ln+WiehjUYDKyYm5vjVGa1l0JZSBtFbJWJ8OFdXkajkRVzc3OiKP4xW/4lQeRURpFXrOTkZLk+NsU2bygU+uMN5vz8vHSHkZqayqmMIoO1ffv2GG4zVy4rK0uqvV5v5OYPHz5I21fbtm3jVEaRwcrPz5e2H5ubm9md1yooLCyU6qampsjNbrf7t1seKqHIYOn1eqvVyurh4eE7d+5EaHY4HCaTKTs7+8CBA9L2Zmw2b94sbYp6PJ7Ozs5wnT6f7/Hjx6zesGHD7t27ObVR6GMzvb29Wu0/7wqtVnvv3r3fnsTtdsfFxbG2NWvW+P3+FX5X2NLS8sfvCj9//rxlyxapzel0iuqj1GCJonj9+vWl75DDhw+3tLSMj4//+PHj27dvL168OHHixNKGxsZGWZ7Hkr6rYZtV58+fZ09VCILw6dOny5cvS7sMHMft3bs3GAyK6qPgYIVCocrKSi46tbW1vwyPOViBQOD48ePRTFpQUDA5OSmqkiI/YzEajaa+vv7+/ftpaWkR2tavX9/U1FRXVyfXvHq93uPx3L59OzExMVwPz/MOh6O9vX3t2rWcKilyg3Qpu91eWlr69OnTV69effz4cXR0dHZ21mAwbNy4MScn58iRIydPnpSe3JKLRqO5ePHi2bNn3W7369evfT7f2NhYMBhMSUnZsWPHwYMHbTbb0s02FdLgf0IDBQUvhfBfhmABCQQLSCBYQALBAhIIFpBAsIAEggUkECwggWABCQQLSCBYQALBAhIIFpBAsIAEggUkECwggWABCQQLSCBYQALBAhIIFpBAsIAEggUkECwggWABCQQLOAo/AcPczS8f0SU1AAAAAElFTkSuQmCC"


def _hello_png_base64() -> str:
    """Return a 200x80 PNG (Base64) of the word 'Hello' in black on white.

    Baked in at build time (PIL + Arial on the developer's box) so the Test
    OCR button always sends a recognisable image regardless of what fonts
    are installed on the user's machine.
    """
    return _HELLO_PNG_B64


def _normalise_endpoint(url: str) -> str:
    """Append ``/v1`` to local OpenAI-compatible endpoints that are missing it.

    LM Studio, Ollama, vLLM, llama.cpp and friends serve the OpenAI-compatible
    API at ``/v1``. Users routinely paste just ``http://localhost:1234`` and
    then get an opaque ConnectionError because the SDK requests
    ``http://localhost:1234/chat/completions`` which 404s.
    """
    if not url:
        return url
    url = url.rstrip("/")
    if not url:
        return url
    # If the URL already has any path component, trust the user.
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.path and parsed.path not in ("/",):
        return url
    return url + "/v1"


def _diagnose_test_error(exc: Exception, endpoint: str, model: str) -> str:
    name = type(exc).__name__
    msg = str(exc).lower()

    if (
        "memory" in msg
        or "out of memory" in msg
        or "oom" in msg
        or "cuda out of memory" in msg
    ):
        return (
            f"The model '{model}' doesn't fit in available RAM/VRAM.\n"
            "Pick a smaller vision-capable model. From smallest:\n"
            "  • moondream         (~1.7B params, ~1.5 GB)\n"
            "  • minicpm-v         (~3B,  ~3 GB)\n"
            "  • gemma3:4b         (~4B,  ~3 GB) — vision-enabled\n"
            "  • llava:7b-q4_0     (~7B,  ~4 GB quantised)\n"
            "  • qwen2.5vl:7b      (~7B,  ~5 GB)\n"
            "Close other apps to free RAM, or use a quantised variant."
        )

    if "connection" in name.lower() or "connection" in msg:
        if endpoint:
            return (
                "Common causes:\n"
                f"  • The local server isn't running on {endpoint}.\n"
                "  • The endpoint path is wrong. LM Studio, Ollama, vLLM and\n"
                "    llama.cpp all expose the OpenAI API at '/v1'.\n"
                "    Try: http://localhost:1234/v1  (LM Studio default).\n"
                "  • A firewall is blocking the port."
            )
        return (
            "Couldn't reach the OpenAI API. Check your internet connection or\n"
            "set a local endpoint (e.g. http://localhost:1234/v1 for LM Studio)."
        )

    if "auth" in name.lower() or "401" in msg or "unauthorized" in msg:
        return (
            "The API key was rejected. Check the key field, or for cloud\n"
            "providers verify the key has access to the configured model."
        )

    if "404" in msg or "not found" in msg or "does not exist" in msg:
        return (
            f"The model '{model}' wasn't found on the server.\n"
            "  • For LM Studio: copy the model identifier from the\n"
            "    'Local Server' tab (case-sensitive).\n"
            "  • For Ollama: use the tag you pulled, e.g. 'gemma3:4b'.\n"
            "  • For OpenAI / Azure: confirm the model name is correct."
        )

    if "timeout" in name.lower() or "timed out" in msg:
        return (
            "The model didn't respond within 60 seconds. Vision-capable\n"
            "models on CPU can be very slow; try a smaller model or wait."
        )

    return (
        "Check that the endpoint URL, model name, and API key are correct.\n"
        "For LM Studio the URL should end with '/v1'."
    )


class FileListDelegate(QStyledItemDelegate):
    """Paints a small Peach-coloured ``SCAN`` pill on items marked as scanned.

    Colours are pulled from the active Catppuccin palette at paint time so a
    flavor switch propagates without rebuilding the delegate.
    """

    BADGE_TEXT = "SCAN"
    BADGE_MARGIN_RIGHT = 8
    BADGE_PAD_X = 8
    BADGE_PAD_Y = 2

    @staticmethod
    def _badge_fill() -> QColor:
        # Peach reads as "warn/special handling" without being alarming
        # like Red. The semantic role of the badge is "this PDF will be
        # OCR'd, not text-extracted".
        return QColor(current_palette().peach)

    @staticmethod
    def _badge_text_color() -> QColor:
        # Base for dark flavors, Crust for Latte — Catppuccin's standard
        # text-on-accent foreground.
        p = current_palette()
        return QColor(p.base if p.is_dark else p.crust)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        if index.data(SCANNED_ROLE):
            badge_w, badge_h = self._badge_size(opt)
            opt.rect = QRect(
                opt.rect.left(),
                opt.rect.top(),
                opt.rect.width() - badge_w - self.BADGE_MARGIN_RIGHT * 2,
                opt.rect.height(),
            )

        super().paint(painter, opt, index)

        if not index.data(SCANNED_ROLE):
            return

        full_rect = option.rect
        badge_w, badge_h = self._badge_size(opt)
        x = full_rect.right() - badge_w - self.BADGE_MARGIN_RIGHT
        y = full_rect.center().y() - badge_h // 2 + 1
        rect = QRect(x, y, badge_w, badge_h)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.setBrush(self._badge_fill())
        painter.drawRoundedRect(rect, badge_h / 2, badge_h / 2)
        painter.setPen(self._badge_text_color())
        painter.setFont(self._badge_font(option.font))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.BADGE_TEXT)
        painter.restore()

    def _badge_font(self, base: QFont) -> QFont:
        f = QFont(base)
        f.setPointSize(max(7, base.pointSize() - 2))
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        return f

    def _badge_size(self, option: QStyleOptionViewItem) -> tuple[int, int]:
        fm = option.fontMetrics
        f = self._badge_font(option.font)
        # Approx using base font metrics is good enough for sizing.
        w = fm.horizontalAdvance(self.BADGE_TEXT) + self.BADGE_PAD_X * 2
        h = fm.height() + self.BADGE_PAD_Y * 2
        _ = f  # silence unused
        return w, h


SUPPORTED_EXTENSIONS = [
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".csv", ".tsv",
    ".html", ".htm", ".xml", ".json",
    ".txt", ".md", ".rtf",
    ".epub",
    ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".gif",
    ".mp3", ".wav", ".m4a", ".flac",
    ".zip",
]

FILE_DIALOG_FILTER = (
    "Supported files ("
    + " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
    + ");;All files (*.*)"
)


def _svg_pixmap(svg: str, size: QSize) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def _folder_label(rel_dir: str) -> str:
    return rel_dir.rsplit("/", 1)[-1] if rel_dir else "(top level)"


class IndexFoldersDialog(QDialog):
    """Pick which output folders get sidecar ``.index.md`` files.

    Each folder's checkbox covers the files directly inside it. Ticking or
    unticking a folder applies the same to every folder below it, after
    which subfolders can still be changed one by one.
    """

    def __init__(
        self,
        parent: QWidget,
        file_counts: dict[str, int],
        excluded: set[str],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate index.md per folder")
        self.resize(520, 480)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Tick the folders whose large files should get a sidecar "
            "<name>.index.md. Changing a folder also changes every folder "
            "inside it."
        )
        hint.setWordWrap(True)
        hint.setObjectName("HintLabel")
        layout.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder", "Queued files"])
        layout.addWidget(self.tree, stretch=1)

        # Every ancestor of a queued folder appears, even without files of
        # its own, so the tree matches the output directory.
        folders = set(file_counts)
        for rel in list(folders):
            parts = PurePosixPath(rel).parts if rel else ()
            for depth in range(len(parts)):
                folders.add("/".join(parts[:depth]))
        self._items: dict[str, QTreeWidgetItem] = {}
        for rel in sorted(folders, key=lambda r: (r.count("/") if r else -1, r.lower())):
            parent_rel = rel.rpartition("/")[0] if "/" in rel else ("" if rel else None)
            item = QTreeWidgetItem([_folder_label(rel), str(file_counts.get(rel, 0))])
            item.setData(0, Qt.ItemDataRole.UserRole, rel)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.CheckState.Unchecked if rel in excluded else Qt.CheckState.Checked,
            )
            if parent_rel is None:
                self.tree.addTopLevelItem(item)
            else:
                self._items[parent_rel].addChild(item)
            self._items[rel] = item
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        self.tree.itemChanged.connect(self._cascade)

        buttons = QHBoxLayout()
        all_btn = QPushButton("All")
        all_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        none_btn = QPushButton("None")
        none_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        buttons.addWidget(all_btn)
        buttons.addWidget(none_btn)
        buttons.addStretch(1)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def _cascade(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        state = item.checkState(0)
        self.tree.blockSignals(True)
        stack = [item.child(i) for i in range(item.childCount())]
        while stack:
            child = stack.pop()
            child.setCheckState(0, state)
            stack.extend(child.child(i) for i in range(child.childCount()))
        self.tree.blockSignals(False)
        self.tree.viewport().update()

    def _set_all(self, state: Qt.CheckState) -> None:
        self.tree.blockSignals(True)
        for item in self._items.values():
            item.setCheckState(0, state)
        self.tree.blockSignals(False)
        self.tree.viewport().update()

    def folders(self) -> set[str]:
        return set(self._items)

    def excluded(self) -> set[str]:
        return {
            rel for rel, item in self._items.items()
            if item.checkState(0) != Qt.CheckState.Checked
        }


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"MarkItDown  v{__version__}")
        self.resize(960, 720)
        # The Catppuccin stylesheet is set on QApplication in app/main.py;
        # we don't override it per-window so flavor switches reach every
        # widget without an extra hop.

        self._thread = None
        self._worker: ConversionWorker | None = None

        # Google Drive source. Sign-in and listing run on daemon threads
        # (see _toggle_gdrive_sign_in); the workers are kept referenced here
        # until they report back.
        self._signin_worker: SignInWorker | None = None
        self._drive_list_worker: DriveListWorker | None = None
        self._gdrive_account = ""
        # Output folders (relative POSIX paths, "" = top level) whose files
        # get no sidecar index even though "Generate index.md" is on.
        self._index_excluded: set[str] = set()

        self._scan_detector = ScanDetector(max_workers=2)
        self._scan_detector.result_ready.connect(self._on_scan_result)

        self._llm_discovery = LocalLLMDiscovery()
        self._llm_discovery.finished.connect(self._on_llm_discovery_done)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_hero())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 24, 32, 16)
        body_layout.setSpacing(18)

        body_layout.addLayout(self._build_directory_row("Input directory",
                                                       "input_dir", self._pick_input))
        body_layout.addLayout(self._build_directory_row("Output directory",
                                                       "output_dir", self._pick_output))
        body_layout.addLayout(self._build_gdrive_rows())

        body_layout.addWidget(self._build_section_label("Files to convert"))
        body_layout.addLayout(self._build_file_controls())
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setMinimumHeight(180)
        self.file_list.setItemDelegate(FileListDelegate(self.file_list))
        body_layout.addWidget(self.file_list, stretch=2)

        self.overwrite_check = QCheckBox("Overwrite existing .md files")
        self.mirror_check = QCheckBox("Mirror input folder structure in output")
        self.mirror_check.setChecked(True)
        self.generate_index_check = QCheckBox("Generate index.md for large files")
        self.generate_index_check.setChecked(True)
        self.generate_index_check.setToolTip(
            "For converted files over ~500 lines, write a sidecar\n"
            "<name>.index.md listing headings and API endpoints with\n"
            "line numbers so Claude can jump straight to relevant sections.\n"
            "The document's own table of contents is removed from the main\n"
            "file, since the sidecar index replaces it.\n"
            "Use 'Folders…' to switch it on or off per output folder."
        )
        self.index_folders_button = QPushButton("Folders…")
        self.index_folders_button.setToolTip(
            "Choose which output folders get index files — available when\n"
            "the queued files span subfolders and the folder structure is\n"
            "mirrored."
        )
        self.index_folders_button.clicked.connect(self._pick_index_folders)
        self.generate_index_check.toggled.connect(self._refresh_index_folders)
        self.mirror_check.toggled.connect(self._refresh_index_folders)

        self.detect_tables_check = QCheckBox("Detect tables in PDFs")
        self.detect_tables_check.setChecked(True)
        self.detect_tables_check.setToolTip(
            "Use pdfplumber to find ruled tables in PDFs and emit them as\n"
            "Markdown tables instead of a vertical list of cells."
        )
        self.embed_images_check = QCheckBox("Embed document images as base64")
        self.embed_images_check.setChecked(False)
        self.embed_images_check.setToolTip(
            "Extract embedded images from PDF, DOCX, PPTX, XLSX and EPUB\n"
            "files and append them to the Markdown as base64 data: URIs.\n"
            "Output stays self-contained (no separate image files).\n"
            "PDFs require PyMuPDF; other formats use stdlib only."
        )
        self.extract_images_check = QCheckBox("Extract document images to files")
        self.extract_images_check.setChecked(False)
        self.extract_images_check.setToolTip(
            "Extract embedded images from PDF, DOCX, PPTX, XLSX and EPUB\n"
            "files into an 'images/' subfolder next to the .md, and link\n"
            "them from the Markdown with relative paths. Keeps the .md\n"
            "small. PDFs are rasterised to PNG (requires PyMuPDF); other\n"
            "formats preserve the original image bytes and extension."
        )
        # The two image modes are mutually exclusive — base64 inlines the image,
        # file extraction links to it. Ticking one clears the other.
        self.embed_images_check.toggled.connect(self._on_embed_images_toggled)
        self.extract_images_check.toggled.connect(self._on_extract_images_toggled)

        self.strip_pagenumbers_check = QCheckBox("Strip page numbers in PDFs")
        self.strip_pagenumbers_check.setChecked(False)
        self.strip_pagenumbers_check.setToolTip(
            "Remove standalone page-number lines (e.g. '5', '- 5 -',\n"
            "'Page 5', 'Page 5 of 20', '5/20') that PDF text extraction\n"
            "often leaves as their own paragraphs. Only lines isolated by\n"
            "blank lines above and below are removed, so numbers inside\n"
            "paragraphs, tables and list items are left alone."
        )

        self.normalize_headings_check = QCheckBox("Normalise heading structure")
        self.normalize_headings_check.setChecked(True)
        self.normalize_headings_check.setToolTip(
            "Give every file one top-level heading and no skipped levels\n"
            "(markdownlint MD025 / MD001):\n"
            "  • a Word / Google Docs 'Title' paragraph becomes the # heading\n"
            "    and Heading 1-5 move down one level;\n"
            "  • a file with several # headings gets its name as the # heading\n"
            "    and every heading moves down one level;\n"
            "  • skipped levels (H1 -> H3) are closed up, keeping which headings\n"
            "    are siblings and which are children.\n"
            "Untick to keep the source document's heading levels as they are."
        )

        self.strip_headers_footers_check = QCheckBox(
            "Strip headers/footers in PDFs/DOCX"
        )
        self.strip_headers_footers_check.setChecked(False)
        self.strip_headers_footers_check.setToolTip(
            "Remove running headers and footers — lines that repeat across\n"
            "pages, such as a signature banner or document title bar. PDF\n"
            "text extraction re-emits these inline on every page; DOCX files\n"
            "exported from a PDF (or built page-by-page with a banner typed\n"
            "into the body) show the same pattern. A line is removed only\n"
            "when it recurs 3+ times and is not a heading or list item, so\n"
            "unique body text is never touched. Headers/footers on documents\n"
            "with fewer than 3 pages stay (too few repeats to tell them apart\n"
            "from real content)."
        )

        # Wrapping rows: in a narrow window (e.g. half a screen under a
        # tiling window manager) the options flow onto more lines instead of
        # being cut off or drawn over each other.
        general_row = FlowLayout()
        for widget in (
            self.overwrite_check,
            self.mirror_check,
            group(self.generate_index_check, self.index_folders_button),
            self.normalize_headings_check,
        ):
            general_row.addWidget(widget)
        body_layout.addLayout(general_row)

        pdf_row = FlowLayout()
        for widget in (
            self.detect_tables_check,
            self.embed_images_check,
            self.extract_images_check,
            self.strip_pagenumbers_check,
            self.strip_headers_footers_check,
        ):
            pdf_row.addWidget(widget)
        body_layout.addLayout(pdf_row)

        body_layout.addLayout(self._build_ocr_row())

        body_layout.addWidget(self._build_section_label("Progress"))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m")
        body_layout.addWidget(self.progress)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(140)
        body_layout.addWidget(self.log_view, stretch=1)


        # Scroll rather than squeeze: the options need ~1200 px of height,
        # and a tiling window manager (sway, i3) sizes the window to its tile
        # regardless of that minimum — Qt then draws rows over each other
        # (the option row landing inside the file list). In a scroll area
        # the content keeps its minimum and a scrollbar appears instead.
        scroll = QScrollArea()
        scroll.setObjectName("BodyScroll")
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Transparent, so the window's Catppuccin background shows through.
        scroll.setStyleSheet(
            "QScrollArea#BodyScroll, QScrollArea#BodyScroll > QWidget > QWidget"
            " { background: transparent; }"
        )
        scroll.viewport().setAutoFillBackground(False)
        body.setAutoFillBackground(False)
        root.addWidget(scroll, stretch=1)

        # Count / Cancel / Convert stay outside the scroll area, so they are
        # always visible however short the window is.
        actions = QWidget()
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(32, 8, 32, 12)
        actions_layout.addLayout(self._build_action_row())
        root.addWidget(actions)

        status = QStatusBar()
        status.showMessage("Ready.")
        self.setStatusBar(status)
        self._add_theme_picker(status)

        # Debounced auto-save: every change schedules a write 500 ms later.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._persist_settings)
        self._suppress_save = True
        self._load_settings()
        self._wire_persistence_signals()
        self._suppress_save = False
        self._refresh_gdrive_account()
        self._refresh_index_folders()
        self.input_dir.textChanged.connect(self._refresh_index_folders)

    # --- Theme picker -------------------------------------------------

    def _add_theme_picker(self, status: QStatusBar) -> None:
        """Add a "Theme: [Flavor] / [Accent]" picker to the status bar's
        right-hand side. Swaps the entire Catppuccin theme at runtime."""
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(6)

        row.addWidget(QLabel("Theme:"))
        self.flavor_combo = QComboBox()
        for flavor in (Flavor.LATTE, Flavor.FRAPPE, Flavor.MACCHIATO, Flavor.MOCHA):
            self.flavor_combo.addItem(PALETTES[flavor].name, flavor)
        self.flavor_combo.setCurrentText(current_palette().name)
        self.flavor_combo.setToolTip(
            "Catppuccin flavor — Latte (light), Frappé / Macchiato / Mocha (dark)."
        )
        self.flavor_combo.currentIndexChanged.connect(self._on_theme_changed)
        row.addWidget(self.flavor_combo)

        self.accent_combo = QComboBox()
        for accent in ACCENTS:
            self.accent_combo.addItem(accent.capitalize(), accent)
        from .theme import current_accent_name
        idx = self.accent_combo.findData(current_accent_name())
        if idx >= 0:
            self.accent_combo.setCurrentIndex(idx)
        self.accent_combo.setToolTip("Accent colour — drives buttons, links, selection.")
        self.accent_combo.currentIndexChanged.connect(self._on_theme_changed)
        row.addWidget(self.accent_combo)

        status.addPermanentWidget(wrapper)

    def _on_theme_changed(self) -> None:
        flavor = self.flavor_combo.currentData()
        accent = self.accent_combo.currentData()
        if flavor is None or accent is None:
            return
        app = QApplication.instance()
        if app is None:
            return
        apply_catppuccin(app, flavor, accent)
        refresh_widgets(app.allWidgets())
        self._refresh_hero_logo()
        self.file_list.viewport().update()  # repaint SCAN badges
        self._schedule_save()

    def _refresh_hero_logo(self) -> None:
        """Re-render the cat silhouette in the active accent."""
        if hasattr(self, "_hero_logo"):
            self._hero_logo.setPixmap(
                _svg_pixmap(catppuccin_cat_svg(current_accent_hex()), QSize(48, 48))
            )

    # --- Settings persistence -----------------------------------------

    def _wire_persistence_signals(self) -> None:
        for line in (self.input_dir, self.output_dir,
                     self.ocr_endpoint_edit, self.ocr_key_edit,
                     self.gdrive_url_edit, self.gdrive_client_edit):
            line.textChanged.connect(self._schedule_save)
        for cb in (self.overwrite_check, self.mirror_check,
                   self.detect_tables_check, self.generate_index_check,
                   self.embed_images_check, self.extract_images_check,
                   self.strip_pagenumbers_check,
                   self.strip_headers_footers_check,
                   self.normalize_headings_check, self.ocr_check):
            cb.toggled.connect(self._schedule_save)
        self.ocr_provider_combo.currentIndexChanged.connect(self._schedule_save)
        self.ocr_model_combo.currentTextChanged.connect(self._schedule_save)

    def _schedule_save(self) -> None:
        if self._suppress_save:
            return
        self._save_timer.start()

    def _persist_settings(self) -> None:
        flavor_data = self.flavor_combo.currentData() if hasattr(self, "flavor_combo") else None
        accent_data = self.accent_combo.currentData() if hasattr(self, "accent_combo") else None
        data = {
            "input_dir": self.input_dir.text(),
            "output_dir": self.output_dir.text(),
            "overwrite": self.overwrite_check.isChecked(),
            "mirror": self.mirror_check.isChecked(),
            "detect_tables": self.detect_tables_check.isChecked(),
            "generate_index": self.generate_index_check.isChecked(),
            "embed_images": self.embed_images_check.isChecked(),
            "extract_images": self.extract_images_check.isChecked(),
            "strip_pagenumbers": self.strip_pagenumbers_check.isChecked(),
            "strip_headers_footers": self.strip_headers_footers_check.isChecked(),
            "normalize_headings": self.normalize_headings_check.isChecked(),
            "index_excluded_folders": sorted(self._index_excluded),
            "gdrive": {
                "folder_url": self.gdrive_url_edit.text(),
                "client_file": self.gdrive_client_edit.text(),
                "account": self._gdrive_account,
            },
            "theme": {
                "flavor": flavor_data.value if isinstance(flavor_data, Flavor) else "mocha",
                "accent": accent_data if isinstance(accent_data, str) else "mauve",
            },
            "ocr": {
                "enabled": self.ocr_check.isChecked(),
                "provider": self.ocr_provider_combo.currentText(),
                "endpoint": self.ocr_endpoint_edit.text(),
                "model": self.ocr_model_combo.currentText(),
                "api_key": self.ocr_key_edit.text(),
            },
        }
        save_config(data)

    def _load_settings(self) -> None:
        cfg = load_config()
        if not cfg:
            return
        if "input_dir" in cfg:
            self.input_dir.setText(cfg["input_dir"])
        if "output_dir" in cfg:
            self.output_dir.setText(cfg["output_dir"])
        for key, widget in (
            ("overwrite", self.overwrite_check),
            ("mirror", self.mirror_check),
            ("detect_tables", self.detect_tables_check),
            ("generate_index", self.generate_index_check),
            ("embed_images", self.embed_images_check),
            ("extract_images", self.extract_images_check),
            ("strip_pagenumbers", self.strip_pagenumbers_check),
            ("strip_headers_footers", self.strip_headers_footers_check),
            ("normalize_headings", self.normalize_headings_check),
        ):
            if key in cfg:
                widget.setChecked(bool(cfg[key]))
        self._index_excluded = {
            str(rel) for rel in cfg.get("index_excluded_folders") or []
        }
        gdrive = cfg.get("gdrive") or {}
        self.gdrive_url_edit.setText(str(gdrive.get("folder_url") or ""))
        self.gdrive_client_edit.setText(str(gdrive.get("client_file") or ""))
        self._gdrive_account = str(gdrive.get("account") or "")
        ocr = cfg.get("ocr") or {}
        if "enabled" in ocr:
            self.ocr_check.setChecked(bool(ocr["enabled"]))
            # Manually fire the toggle so dependent fields enable/disable.
            self._on_ocr_toggled(self.ocr_check.isChecked())
        if ocr.get("provider"):
            idx = self.ocr_provider_combo.findText(ocr["provider"])
            if idx >= 0:
                self.ocr_provider_combo.setCurrentIndex(idx)
        # Endpoint / model are set AFTER provider so the user's saved values
        # override the preset's defaults if they had customised them.
        if "endpoint" in ocr:
            self.ocr_endpoint_edit.setText(ocr["endpoint"])
        if ocr.get("model"):
            if self.ocr_model_combo.findText(ocr["model"]) < 0:
                self.ocr_model_combo.insertItem(0, ocr["model"])
            self.ocr_model_combo.setCurrentText(ocr["model"])
        if "api_key" in ocr:
            self.ocr_key_edit.setText(ocr["api_key"])

        # Theme: apply the saved flavor/accent and sync the combos. The
        # theme is also applied in app/main.py at startup, but redoing it
        # here is cheap and keeps the combos as the single source of truth.
        theme = cfg.get("theme") or {}
        if theme.get("flavor") or theme.get("accent"):
            flavor = Flavor.from_name(theme.get("flavor"))
            accent = theme.get("accent") or "mauve"
            if accent not in ACCENTS:
                accent = "mauve"
            f_idx = self.flavor_combo.findData(flavor)
            if f_idx >= 0:
                self.flavor_combo.setCurrentIndex(f_idx)
            a_idx = self.accent_combo.findData(accent)
            if a_idx >= 0:
                self.accent_combo.setCurrentIndex(a_idx)
            # Apply for real (combo changes during suppress don't fire the slot).
            app = QApplication.instance()
            if app is not None:
                apply_catppuccin(app, flavor, accent)
                refresh_widgets(app.allWidgets())
                self._refresh_hero_logo()

    # --- UI builders ---------------------------------------------------

    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("HeroFrame")
        hero.setFixedHeight(110)
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(32, 18, 32, 18)
        layout.setSpacing(20)

        logo_label = QLabel()
        # Cat silhouette in the active accent — re-rendered on flavor/accent
        # change via `_refresh_hero_logo()`.
        self._hero_logo = logo_label
        self._refresh_hero_logo()
        logo_label.setStyleSheet("background: transparent;")
        layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        title = QLabel("MarkItDown")
        title.setObjectName("HeroTitle")
        subtitle = QLabel(
            "Convert PDFs, Office documents, images and more to clean Markdown."
        )
        subtitle.setObjectName("HeroSubtitle")
        text_box.addWidget(title)
        text_box.addWidget(subtitle)
        text_box.addStretch(1)
        layout.addLayout(text_box, stretch=1)

        return hero

    def _build_section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        return label

    def _build_directory_row(self, label_text: str, attr: str, callback) -> QVBoxLayout:
        row = QVBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._build_section_label(label_text))

        inner = QHBoxLayout()
        edit = QLineEdit()
        edit.setPlaceholderText("Select a folder…")
        setattr(self, attr, edit)
        browse = QPushButton("Browse…")
        browse.clicked.connect(callback)
        inner.addWidget(edit, stretch=1)
        inner.addWidget(browse)
        row.addLayout(inner)
        return row

    def _build_gdrive_rows(self) -> QVBoxLayout:
        outer = QVBoxLayout()
        outer.setSpacing(6)
        outer.addWidget(self._build_section_label("Google Drive source"))

        top = QHBoxLayout()
        self.gdrive_url_edit = QLineEdit()
        self.gdrive_url_edit.setPlaceholderText(
            "https://drive.google.com/drive/folders/…  (folder in My Drive or a Shared Drive)"
        )
        self.gdrive_url_edit.setToolTip(
            "The Drive folder to convert. 'Add from Drive' queues every Google\n"
            "Doc, Sheet and Slides file in it and in all its subfolders, plus\n"
            "uploaded files in a supported format. The output directory gets\n"
            "the same folder tree, one .md per file — the reverse of\n"
            "Confluence L33ch's 'Upload to Google Docs'."
        )
        top.addWidget(self.gdrive_url_edit, stretch=1)
        self.gdrive_add_button = QPushButton("Add from Drive")
        self.gdrive_add_button.clicked.connect(self._add_from_drive)
        top.addWidget(self.gdrive_add_button)
        self.gdrive_signin_button = QPushButton("Sign in…")
        self.gdrive_signin_button.clicked.connect(self._toggle_gdrive_sign_in)
        top.addWidget(self.gdrive_signin_button)
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("OAuth client:"))
        self.gdrive_client_edit = QLineEdit()
        self.gdrive_client_edit.setPlaceholderText(
            "client_secret_….json  (Desktop-app OAuth client, Drive API enabled)"
        )
        self.gdrive_client_edit.setToolTip(
            "The OAuth client file Google sign-in needs: a 'Desktop app' OAuth\n"
            "client in a Google Cloud project with the Google Drive API enabled.\n"
            "Access requested is read-only\n"
            "(https://www.googleapis.com/auth/drive.readonly)."
        )
        bottom.addWidget(self.gdrive_client_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_gdrive_client)
        bottom.addWidget(browse)
        outer.addLayout(bottom)

        self.gdrive_account_label = QLabel("")
        self.gdrive_account_label.setObjectName("HintLabel")
        outer.addWidget(self.gdrive_account_label)
        return outer

    def _build_ocr_row(self) -> QVBoxLayout:
        outer = QVBoxLayout()
        outer.setSpacing(6)
        top = QHBoxLayout()
        self.ocr_check = QCheckBox("OCR images in PDFs && image files (LLM vision)")
        self.ocr_check.setChecked(False)
        self.ocr_check.setToolTip(
            "Extract text from scanned PDFs and from standalone image files\n"
            "(.png, .jpg, .jpeg) by sending them to an OpenAI-compatible\n"
            "vision model, transcribing the text into structured Markdown.\n"
            "Requires markitdown-ocr + openai packages."
        )
        self.ocr_check.toggled.connect(self._on_ocr_toggled)
        top.addWidget(self.ocr_check)
        top.addStretch(1)
        self.ocr_test_button = QPushButton("Test OCR")
        self.ocr_test_button.setToolTip(
            "Send one tiny image to the configured model and show the response.\n"
            "Use this to verify your endpoint/model/key without converting a real file."
        )
        self.ocr_test_button.clicked.connect(self._test_ocr)
        top.addWidget(self.ocr_test_button)
        outer.addLayout(top)

        # Each label stays with its field; the groups wrap in a narrow window.
        fields = FlowLayout(h_spacing=16, v_spacing=8)

        provider_lbl = QLabel("Provider:")
        self.ocr_provider_combo = QComboBox()
        for preset in PROVIDER_PRESETS:
            self.ocr_provider_combo.addItem(preset.name)
        self.ocr_provider_combo.setToolTip(
            "One-click preset for common providers. Picking one fills in the\n"
            "endpoint and a default vision model. You still need to paste your\n"
            "own API key."
        )
        self.ocr_provider_combo.currentIndexChanged.connect(self._apply_provider_preset)

        model_lbl = QLabel("Model:")
        self.ocr_model_combo = QComboBox()
        self.ocr_model_combo.setEditable(True)
        self.ocr_model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.ocr_model_combo.addItem("gpt-4o")
        self.ocr_model_combo.setCurrentText("gpt-4o")
        self.ocr_model_combo.setMinimumWidth(200)
        self.ocr_model_combo.setToolTip(
            "Type a model name or pick one from the dropdown.\n"
            "Click 'Detect local LLMs' to fill the list from a running\n"
            "LM Studio / Ollama / vLLM / llama.cpp server."
        )

        endpoint_lbl = QLabel("Endpoint:")
        self.ocr_endpoint_edit = QLineEdit()
        # A flow layout doesn't stretch fields, so give the URL room.
        self.ocr_endpoint_edit.setMinimumWidth(340)
        self.ocr_endpoint_edit.setPlaceholderText(
            "(blank = OpenAI default; LM Studio: http://localhost:1234/v1; "
            "Ollama: http://localhost:11434/v1)"
        )

        self.ocr_detect_button = QPushButton("Detect")
        self.ocr_detect_button.setToolTip(
            "Probe localhost for running LM Studio / Ollama / vLLM /\n"
            "llama.cpp servers and list their vision-capable models."
        )
        self.ocr_detect_button.clicked.connect(self._detect_local_llms)

        key_lbl = QLabel("API key:")
        self.ocr_key_edit = QLineEdit()
        self.ocr_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ocr_key_edit.setPlaceholderText("(blank = use OPENAI_API_KEY env var)")
        self.ocr_key_edit.setFixedWidth(220)
        self.ocr_key_edit.setToolTip(
            "Saved to disk in your config file (plain text). "
            "Leave blank to use the OPENAI_API_KEY environment variable instead."
        )

        for widgets in ((provider_lbl, self.ocr_provider_combo),
                        (model_lbl, self.ocr_model_combo),
                        (endpoint_lbl, self.ocr_endpoint_edit, self.ocr_detect_button),
                        (key_lbl, self.ocr_key_edit)):
            fields.addWidget(group(*widgets))
        outer.addLayout(fields)

        self._ocr_field_widgets = [
            provider_lbl, self.ocr_provider_combo,
            model_lbl, self.ocr_model_combo,
            endpoint_lbl, self.ocr_endpoint_edit,
            self.ocr_detect_button,
            key_lbl, self.ocr_key_edit,
            self.ocr_test_button,
        ]
        self._on_ocr_toggled(False)
        return outer

    def _apply_provider_preset(self, index: int) -> None:
        """Fill endpoint + model from the selected provider preset."""
        if index <= 0 or index >= len(PROVIDER_PRESETS):
            return
        preset = PROVIDER_PRESETS[index]
        self.ocr_endpoint_edit.setText(preset.endpoint)
        if preset.model:
            self.ocr_model_combo.blockSignals(True)
            # Don't wipe other items the user might have populated via Detect;
            # just add the preset model and select it.
            if self.ocr_model_combo.findText(preset.model) < 0:
                self.ocr_model_combo.insertItem(0, preset.model)
            self.ocr_model_combo.setCurrentText(preset.model)
            self.ocr_model_combo.blockSignals(False)
        if preset.hint:
            self.statusBar().showMessage(f"{preset.name}: {preset.hint}", 15000)

    def _on_embed_images_toggled(self, on: bool) -> None:
        if on:
            if self.extract_images_check.isChecked():
                self.extract_images_check.setChecked(False)
            # Inline image placement needs the page-aware
            # PdfPlumberTableConverter; auto-tick "Detect tables in PDFs"
            # so the user doesn't have to remember the dependency.
            if not self.detect_tables_check.isChecked():
                self.detect_tables_check.setChecked(True)

    def _on_extract_images_toggled(self, on: bool) -> None:
        if on:
            if self.embed_images_check.isChecked():
                self.embed_images_check.setChecked(False)
            if not self.detect_tables_check.isChecked():
                self.detect_tables_check.setChecked(True)

    def _on_ocr_toggled(self, enabled: bool) -> None:
        for w in getattr(self, "_ocr_field_widgets", []):
            w.setEnabled(enabled)

    def _detect_local_llms(self) -> None:
        """Probe localhost for OpenAI-compatible servers and populate the model list."""
        self.ocr_detect_button.setEnabled(False)
        self.ocr_detect_button.setText("Scanning…")
        self._llm_discovery.submit()

    def _on_llm_discovery_done(self, servers: list[LocalServer]) -> None:
        self.ocr_detect_button.setEnabled(True)
        self.ocr_detect_button.setText("Detect")

        running = [s for s in servers if s.is_running]
        if not running:
            QMessageBox.information(
                self,
                "No local LLM server detected",
                "No OpenAI-compatible server is running on the standard ports "
                "(1234, 11434, 8000, 8080, 5000).\n\n"
                "Start LM Studio (Local Server tab) or Ollama (`ollama serve`) "
                "and try again, or enter the endpoint URL manually.",
            )
            return

        with_vision = [s for s in running if s.vision_models()]
        if not with_vision:
            text_lines = [
                "Found running servers, but none have a vision-capable model "
                "loaded:",
                "",
            ]
            for s in running:
                text_lines.append(f"  • {s.name} ({s.base_url})")
                if s.models:
                    for m in s.models:
                        text_lines.append(f"      - {m}  (not vision)")
                else:
                    text_lines.append("      - (no models loaded)")
            text_lines.extend([
                "",
                "Install a vision model (smallest first — important on low-RAM "
                "machines):",
                "  • ollama pull moondream    (~1.5 GB — fits anywhere)",
                "  • ollama pull minicpm-v    (~3 GB)",
                "  • ollama pull gemma3:4b    (~3 GB — vision-enabled)",
                "  • ollama pull qwen2.5vl:7b (~5 GB)",
                "  • ollama pull llava        (~5 GB)",
                "  • LM Studio: search for 'vision' or 'VL' in the model "
                "browser;",
                "      load it in the Local Server tab.",
            ])
            QMessageBox.warning(
                self,
                "No vision models loaded",
                "\n".join(text_lines),
            )
            return

        chosen = self._choose_server(with_vision) if len(with_vision) > 1 else with_vision[0]
        if not chosen:
            return
        self._apply_server_choice(chosen)

    def _choose_server(self, servers: list[LocalServer]) -> LocalServer | None:
        menu = QMenu(self)
        menu.setTitle("Pick a server")
        actions: dict = {}
        for s in servers:
            label = f"{s.name} — {len(s.vision_models())} vision model(s)"
            act = menu.addAction(label)
            actions[act] = s
        chosen_act = menu.exec(self.ocr_detect_button.mapToGlobal(
            self.ocr_detect_button.rect().bottomLeft()
        ))
        return actions.get(chosen_act)

    def _apply_server_choice(self, server: LocalServer) -> None:
        self.ocr_endpoint_edit.setText(server.base_url)
        if not self.ocr_key_edit.text():
            self.ocr_key_edit.setText("not-needed")

        vision = server.vision_models()
        non_vision = [m for m in server.models if not is_vision_model(m)]

        self.ocr_model_combo.blockSignals(True)
        self.ocr_model_combo.clear()
        for m in vision:
            self.ocr_model_combo.addItem(m)
        if non_vision:
            self.ocr_model_combo.insertSeparator(self.ocr_model_combo.count())
            for m in non_vision:
                # Plain model name as the item value; (not vision) is a tooltip
                # so currentText() always returns the bare model ID.
                self.ocr_model_combo.addItem(m)
                idx = self.ocr_model_combo.count() - 1
                self.ocr_model_combo.setItemData(
                    idx, "Not vision-capable", Qt.ItemDataRole.ToolTipRole
                )
        self.ocr_model_combo.blockSignals(False)

        if vision:
            self.ocr_model_combo.setCurrentText(vision[0])

        self.statusBar().showMessage(
            f"Detected {server.name} at {server.base_url} — "
            f"{len(vision)} vision model(s) available."
        )

    def _test_ocr(self) -> None:
        """Send one tiny image to the configured model and show the response."""
        if not self.ocr_check.isChecked():
            QMessageBox.information(
                self, "OCR not enabled",
                "Tick the OCR checkbox first to test your settings.",
            )
            return

        model = self.ocr_model_combo.currentText().strip() or "gpt-4o"
        if not is_vision_model(model):
            reply = QMessageBox.question(
                self,
                "Model not recognised as vision-capable",
                f"'{model}' does not match any known vision-capable model "
                "pattern. The test will probably fail with an empty response "
                "or an error.\n\nRun the test anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        endpoint = _normalise_endpoint(self.ocr_endpoint_edit.text().strip())
        if endpoint and endpoint != self.ocr_endpoint_edit.text().strip():
            self.ocr_endpoint_edit.setText(endpoint)
        api_key = self.ocr_key_edit.text() or os.environ.get("OPENAI_API_KEY", "")
        if not api_key and not endpoint:
            QMessageBox.warning(
                self, "OCR needs an API key",
                "Provide an API key or set OPENAI_API_KEY in your environment.",
            )
            return

        try:
            from openai import OpenAI
        except ImportError:
            QMessageBox.critical(
                self, "openai not installed",
                "Run: pip install openai markitdown-ocr",
            )
            return

        kwargs = {"api_key": api_key or "not-needed"}
        if endpoint:
            kwargs["base_url"] = endpoint

        png_b64 = _hello_png_base64()

        self.ocr_test_button.setEnabled(False)
        self.ocr_test_button.setText("Testing…")
        QApplication.processEvents()
        try:
            client = OpenAI(**kwargs)
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text",
                         "text": "What word do you see in this image? Reply with just the word."},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                    ],
                }],
                timeout=60,
            )
            answer = (response.choices[0].message.content or "").strip()
            QMessageBox.information(
                self, "OCR test succeeded",
                f"Endpoint: {endpoint or 'OpenAI default'}\n"
                f"Model: {model}\n\n"
                f"Model replied:\n  {answer or '(empty response)'}\n\n"
                + (
                    "Expected: 'Hello'. "
                    "If the reply is empty or unrelated, the model is "
                    "probably not vision-capable."
                    if "hello" not in answer.lower()
                    else "Looks good — OCR is wired up correctly."
                ),
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "OCR test failed",
                f"Endpoint: {endpoint or 'OpenAI default'}\n"
                f"Model: {model}\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                + _diagnose_test_error(exc, endpoint, model),
            )
        finally:
            self.ocr_test_button.setEnabled(True)
            self.ocr_test_button.setText("Test OCR")

    def _ocr_credentials_present(self) -> bool:
        if self.ocr_key_edit.text().strip():
            return True
        if os.environ.get("OPENAI_API_KEY"):
            return True
        # Local endpoints (LM Studio, Ollama) accept any key including blank.
        if self.ocr_endpoint_edit.text().strip():
            return True
        return False

    def _build_file_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        add_files = QPushButton("Add files…")
        add_files.clicked.connect(self._add_files)
        add_folder = QPushButton("Add folder…")
        add_folder.clicked.connect(self._add_folder)
        remove_selected = QPushButton("Remove selected")
        remove_selected.setObjectName("DangerButton")
        remove_selected.clicked.connect(self._remove_selected)
        clear = QPushButton("Clear")
        clear.setObjectName("DangerButton")
        clear.clicked.connect(self.file_list_clear)
        row.addWidget(add_files)
        row.addWidget(add_folder)
        row.addSpacerItem(QSpacerItem(20, 10,
                                      QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Minimum))
        row.addWidget(remove_selected)
        row.addWidget(clear)
        return row

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.count_label = QLabel("0 files queued")
        self.count_label.setObjectName("HintLabel")
        self.convert_button = QPushButton("Convert to Markdown")
        self.convert_button.setObjectName("PrimaryButton")
        self.convert_button.clicked.connect(self._start_conversion)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_conversion)
        row.addWidget(self.count_label)
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        row.addWidget(self.convert_button)
        return row

    # --- Slots ---------------------------------------------------------

    def _pick_input(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose input directory")
        if path:
            self.input_dir.setText(str(Path(path)))
            if not self.output_dir.text():
                self.output_dir.setText(str(Path(path) / "markdown_output"))

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if path:
            self.output_dir.setText(str(Path(path)))

    def _add_files(self) -> None:
        start = self.input_dir.text() or str(Path.home())
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add files", start, FILE_DIALOG_FILTER
        )
        for f in files:
            self._add_path(Path(f))
        self._update_count()

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Add all supported files from folder",
            self.input_dir.text() or str(Path.home()),
        )
        if not folder:
            return
        root = Path(folder)
        if not self.input_dir.text():
            self.input_dir.setText(str(root))
        added = 0
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                self._add_path(p)
                added += 1
        self.statusBar().showMessage(f"Added {added} file(s) from {root}.")
        self._update_count()

    def _add_path(self, path: Path) -> None:
        existing = {self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.file_list.count())}
        if str(path) in existing:
            return
        item = QListWidgetItem(str(path))
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        self.file_list.addItem(item)
        if path.suffix.lower() == ".pdf":
            self._scan_detector.submit(str(path))

    def _on_scan_result(self, path: str, is_scanned: bool) -> None:
        if not is_scanned:
            return
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setData(SCANNED_ROLE, True)
                item.setToolTip(
                    f"{path}\n\nScanned PDF — enable 'OCR images in PDFs' "
                    "to extract text from the page images."
                )
                return

    def closeEvent(self, event) -> None:
        self._scan_detector.shutdown()
        self._llm_discovery.shutdown()
        # Flush any debounced save before the process exits.
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._persist_settings()
        # A conversion still running would abort the process on exit
        # ("QThread: Destroyed while thread is still running"). Cancel it and
        # give the current file a moment; if it is stuck in a long call (an
        # OCR request can take minutes), leave without tearing the thread
        # down — settings are already saved, and only that file is lost.
        if not stop_threads(5000):
            os._exit(0)
        super().closeEvent(event)

    def _remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))
        self._update_count()

    def file_list_clear(self) -> None:
        self.file_list.clear()
        self._update_count()

    def _update_count(self) -> None:
        n = self.file_list.count()
        self.count_label.setText(f"{n} file{'s' if n != 1 else ''} queued")
        self._refresh_index_folders()

    # --- Google Drive --------------------------------------------------

    def _refresh_gdrive_account(self) -> None:
        signed_in = token_path().is_file()
        self.gdrive_signin_button.setText("Sign out" if signed_in else "Sign in…")
        if signed_in:
            who = self._gdrive_account or "a Google account"
            self.gdrive_account_label.setText(f"Signed in to Google as {who}.")
        else:
            self.gdrive_account_label.setText(
                "Not signed in. Choose the OAuth client file, then click 'Sign in…'."
            )

    def _pick_gdrive_client(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the OAuth client file", self.gdrive_client_edit.text(),
            "OAuth client (*.json);;All files (*.*)",
        )
        if path:
            self.gdrive_client_edit.setText(str(Path(path)))

    def _toggle_gdrive_sign_in(self) -> None:
        if token_path().is_file():
            sign_out()
            self._gdrive_account = ""
            self._schedule_save()
            self.log_view.appendPlainText("Signed out of Google.")
            self._refresh_gdrive_account()
            return
        if self._signin_worker is not None:
            return
        client = Path(self.gdrive_client_edit.text().strip())
        if not client.is_file():
            QMessageBox.warning(
                self, "OAuth client file required",
                "Select the OAuth client JSON file first (a 'Desktop app' "
                "OAuth client with the Google Drive API enabled).",
            )
            return
        self.gdrive_signin_button.setEnabled(False)
        self.gdrive_account_label.setText(
            "Waiting for you to approve access in the browser (5 min timeout)…"
        )
        worker = SignInWorker(client)
        worker.finished.connect(self._on_gdrive_signed_in)
        self._signin_worker = worker
        # A daemon Python thread, not a QThread: the browser flow blocks
        # until the user approves (up to its 5-minute timeout) and cannot be
        # interrupted, and a QThread still running at window close aborts
        # the process. The signal is queued back to the GUI thread.
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_gdrive_signed_in(self, email: str, error: str) -> None:
        self._signin_worker = None
        self.gdrive_signin_button.setEnabled(True)
        if error:
            self.log_view.appendPlainText(f"! Google sign-in failed: {error}")
            QMessageBox.warning(self, "Google sign-in failed", error)
        else:
            self._gdrive_account = email
            self._schedule_save()
            self.log_view.appendPlainText(f"Signed in to Google as {email}.")
        self._refresh_gdrive_account()

    def _add_from_drive(self) -> None:
        if self._drive_list_worker is not None:
            return
        folder_id = parse_folder_id(self.gdrive_url_edit.text())
        problem = ""
        if not folder_id:
            problem = (
                "Paste the address of the Google Drive folder, e.g.\n"
                "https://drive.google.com/drive/folders/1AbC…"
            )
        elif not token_path().is_file():
            problem = "Sign in to Google first."
        if problem:
            QMessageBox.warning(self, "Cannot read Google Drive", problem)
            return
        self.gdrive_add_button.setEnabled(False)
        self.gdrive_add_button.setText("Listing…")
        self.statusBar().showMessage("Listing the Google Drive folder…")
        self.log_view.appendPlainText(f"Listing Google Drive folder {folder_id}…")
        worker = DriveListWorker(folder_id, set(SUPPORTED_EXTENSIONS))
        worker.log.connect(self.log_view.appendPlainText)
        worker.finished.connect(self._on_drive_listed)
        self._drive_list_worker = worker
        # Daemon thread for the same reason as sign-in: a slow listing must
        # never hold up closing the window.
        threading.Thread(target=worker.run, daemon=True).start()

    def _on_drive_listed(self, root_name: str, entries: list, error: str) -> None:
        self._drive_list_worker = None
        self.gdrive_add_button.setEnabled(True)
        self.gdrive_add_button.setText("Add from Drive")
        if error:
            self.log_view.appendPlainText(f"! {error}")
            self.statusBar().showMessage("Listing Google Drive failed.")
            QMessageBox.warning(self, "Cannot read Google Drive", error)
            return
        existing = {self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.file_list.count())}
        added = 0
        for data in entries:
            entry = DriveEntry.from_dict(data)
            key = f"gdrive:{entry.file_id}"
            if key in existing:
                continue
            item = QListWidgetItem(entry.display())
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setData(DRIVE_ROLE, data)
            item.setToolTip(
                f"{entry.display()}\n\nConverted to "
                f"{entry.rel_path}.md in the output directory."
            )
            self.file_list.addItem(item)
            added += 1
        if not self.mirror_check.isChecked() and any(
            d.get("rel_dir") for d in entries
        ):
            self.log_view.appendPlainText(
                "! 'Mirror input folder structure' is off — Drive subfolders "
                "will be flattened into the output directory."
            )
        msg = f"Added {added} file(s) from Google Drive folder '{root_name}'."
        self.log_view.appendPlainText(msg)
        self.statusBar().showMessage(msg)
        self._update_count()

    # --- Per-folder index ----------------------------------------------

    def _queued_rel_dir(self, list_item: QListWidgetItem) -> str:
        """The output folder (relative POSIX path, "" = top level) a queued
        file is written to."""
        if not self.mirror_check.isChecked():
            return ""
        drive = list_item.data(DRIVE_ROLE)
        if drive:
            return drive.get("rel_dir", "")
        in_root_text = self.input_dir.text().strip()
        if not in_root_text:
            return ""
        src = Path(list_item.data(Qt.ItemDataRole.UserRole))
        try:
            rel = src.parent.relative_to(Path(in_root_text))
        except ValueError:
            return ""
        return "" if str(rel) == "." else rel.as_posix()

    def _queued_folder_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for i in range(self.file_list.count()):
            rel = self._queued_rel_dir(self.file_list.item(i))
            counts[rel] = counts.get(rel, 0) + 1
        return counts

    def _refresh_index_folders(self, *_args) -> None:
        if not hasattr(self, "index_folders_button"):
            return
        counts = self._queued_folder_counts()
        has_subfolders = any(rel for rel in counts)
        self.index_folders_button.setEnabled(
            self.generate_index_check.isChecked() and has_subfolders
        )
        excluded = {rel for rel in counts if rel in self._index_excluded}
        if self.generate_index_check.isChecked() and has_subfolders and excluded:
            self.index_folders_button.setText(
                f"Folders… ({len(counts) - len(excluded)}/{len(counts)})"
            )
        else:
            self.index_folders_button.setText("Folders…")

    def _pick_index_folders(self) -> None:
        counts = self._queued_folder_counts()
        dialog = IndexFoldersDialog(self, counts, self._index_excluded)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        shown = dialog.folders()
        # Keep exclusions for folders not in the current queue, so queueing
        # a different subset doesn't forget earlier choices.
        self._index_excluded = (self._index_excluded - shown) | dialog.excluded()
        self._schedule_save()
        self._refresh_index_folders()

    # --- Conversion ----------------------------------------------------

    def _collect_items(self) -> list[ConversionItem]:
        if self.file_list.count() == 0:
            return []
        out_text = self.output_dir.text().strip()
        if not out_text:
            return []
        out_root = Path(out_text)
        in_root_text = self.input_dir.text().strip()
        in_root = Path(in_root_text) if in_root_text else None
        mirror = self.mirror_check.isChecked() and in_root is not None

        index_on = self.generate_index_check.isChecked()
        items: list[ConversionItem] = []
        selected = self.file_list.selectedItems()
        # Convert only the rows the user selected; fall back to all
        # rows when nothing is selected.
        list_items = selected if selected else [
            self.file_list.item(i) for i in range(self.file_list.count())
        ]
        for list_item in list_items:
            generate_index = (
                index_on
                and self._queued_rel_dir(list_item) not in self._index_excluded
            )
            drive = list_item.data(DRIVE_ROLE)
            if drive:
                entry = DriveEntry.from_dict(drive)
                rel = entry.rel_path if self.mirror_check.isChecked() else entry.stem
                items.append(ConversionItem(
                    # Replaced by the staged download inside the worker.
                    source=Path(entry.stem + entry.extension),
                    destination=out_root / (rel + ".md"),
                    generate_index=generate_index,
                    drive=entry,
                ))
                continue
            src = Path(list_item.data(Qt.ItemDataRole.UserRole))
            is_scanned = bool(list_item.data(SCANNED_ROLE))
            if mirror:
                try:
                    rel = src.relative_to(in_root)
                    dest = out_root / rel.with_suffix(".md")
                except ValueError:
                    dest = out_root / (src.stem + ".md")
            else:
                dest = out_root / (src.stem + ".md")
            items.append(ConversionItem(
                source=src,
                destination=dest,
                is_scanned=is_scanned,
                generate_index=generate_index,
            ))
        return items

    def _start_conversion(self) -> None:
        if not self.output_dir.text().strip():
            QMessageBox.warning(self, "Output directory required",
                                "Please choose an output directory.")
            return
        items = self._collect_items()
        if not items:
            QMessageBox.information(self, "Nothing to convert",
                                    "Add at least one file before converting.")
            return

        if self.ocr_check.isChecked() and not self._ocr_credentials_present():
            QMessageBox.warning(
                self,
                "OCR needs an API key",
                "OCR is enabled but no API key was provided and the "
                "OPENAI_API_KEY environment variable is not set.\n\n"
                "Either paste a key into the OCR API key field, "
                "set OPENAI_API_KEY in your environment, "
                "or uncheck 'OCR images in PDFs'.",
            )
            return

        self.progress.setRange(0, len(items))
        self.progress.setValue(0)
        self.log_view.clear()
        self.log_view.appendPlainText(
            f"Starting conversion of {len(items)} file(s)…"
        )
        self.convert_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.statusBar().showMessage("Converting…")

        endpoint = _normalise_endpoint(self.ocr_endpoint_edit.text().strip())
        if endpoint and endpoint != self.ocr_endpoint_edit.text().strip():
            self.ocr_endpoint_edit.setText(endpoint)
        worker = ConversionWorker(
            items,
            overwrite=self.overwrite_check.isChecked(),
            detect_pdf_tables=self.detect_tables_check.isChecked(),
            generate_index=self.generate_index_check.isChecked(),
            embed_pdf_images=self.embed_images_check.isChecked(),
            extract_pdf_images=self.extract_images_check.isChecked(),
            strip_pdf_page_numbers=self.strip_pagenumbers_check.isChecked(),
            strip_pdf_headers_footers=self.strip_headers_footers_check.isChecked(),
            normalize_headings=self.normalize_headings_check.isChecked(),
            ocr=OcrConfig(
                enabled=self.ocr_check.isChecked(),
                model=self.ocr_model_combo.currentText().strip() or "gpt-4o",
                api_key=self.ocr_key_edit.text(),
                base_url=endpoint,
            ),
        )
        worker.progress.connect(self._on_progress)
        worker.log.connect(self.log_view.appendPlainText)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        self._thread = run_in_thread(worker)

    def _cancel_conversion(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.statusBar().showMessage("Cancelling…")

    def _on_progress(self, done: int, total: int, current: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        if current:
            self.statusBar().showMessage(f"Converting {current} ({done + 1}/{total})")

    def _on_finished(self, success: int, failure: int) -> None:
        self.convert_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._worker = None
        self._thread = None
        msg = f"Done — {success} succeeded, {failure} failed."
        self.statusBar().showMessage(msg)
        self.log_view.appendPlainText(msg)
        if failure == 0 and success > 0:
            QMessageBox.information(self, "Conversion complete",
                                    f"Converted {success} file(s) successfully.")
        elif failure > 0:
            QMessageBox.warning(self, "Conversion finished with errors",
                                f"{success} succeeded, {failure} failed. "
                                "See the log for details.")
