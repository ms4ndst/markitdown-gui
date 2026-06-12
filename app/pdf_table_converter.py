"""Table-aware PDF -> Markdown converter using pdfplumber.

Strategy
--------
1. Detect tables with ``vertical_strategy="lines"`` and
   ``horizontal_strategy="lines"`` only — never trust text alignment, which
   produces phantom columns on PDFs with zebra-striped row backgrounds.
2. Post-process every detected table:
   * merge alternating "zebra" row pairs whose non-empty cells are
     complementary (PDFs with row shading frequently double the row count),
   * drop columns that are empty across every row,
   * reject the "table" if it ends up with fewer than two columns or two
     data rows — those are bordered text boxes, not tables.
3. Render text per vertical band (above / between / below tables) so
   paragraphs keep their reading order.
4. If detection fails or no tables survive, fall back to plain pdfminer text
   for the whole document — never silently emit a broken table.
"""

from __future__ import annotations

import io
from collections import Counter
from typing import Any, BinaryIO

from markitdown import (
    DocumentConverter,
    DocumentConverterResult,
    StreamInfo,
)

import pdfminer.high_level
import pdfplumber

ACCEPTED_EXTENSIONS = {".pdf"}
ACCEPTED_MIME_PREFIXES = ("application/pdf", "application/x-pdf")

TABLE_SETTINGS_STRICT: dict[str, Any] = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 4,
    "join_tolerance": 4,
    "edge_min_length": 12,
    "min_words_vertical": 1,
    "min_words_horizontal": 1,
    "intersection_tolerance": 5,
}

MIN_COLUMNS = 2
MIN_DATA_ROWS = 1  # data rows below the header


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text.replace("|", "\\|")


def _normalise_rows(rows: list[list[Any]]) -> list[list[str]]:
    if not rows:
        return []
    width = max(len(r) for r in rows)
    return [[_cell(c) for c in row] + [""] * (width - len(row)) for row in rows]


def _drop_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return rows
    width = len(rows[0])
    keep = [c for c in range(width)
            if any(rows[r][c] for r in range(len(rows)))]
    return [[row[c] for c in keep] for row in rows]


def _merge_exclusive_columns(rows: list[list[str]]) -> list[list[str]]:
    """Merge adjacent column pairs that are mutually exclusive per row.

    pdfplumber sometimes detects two columns where the source has only one,
    because header cells are slightly indented relative to data cells. The
    symptom: a row never fills both column ``c`` and ``c+1``. Repeatedly merge
    such pairs until no more can be merged.
    """
    if not rows:
        return rows

    width = len(rows[0])
    if width < 2:
        return rows

    changed = True
    while changed and len(rows[0]) > 1:
        changed = False
        width = len(rows[0])
        for c in range(width - 1):
            both_filled = sum(
                1 for r in rows if r[c] and r[c + 1]
            )
            either_filled = sum(
                1 for r in rows if r[c] or r[c + 1]
            )
            if either_filled >= 2 and both_filled == 0:
                rows = [
                    r[:c] + [r[c] or r[c + 1]] + r[c + 2:]
                    for r in rows
                ]
                changed = True
                break
    return rows


def _merge_zebra_rows(rows: list[list[str]]) -> list[list[str]]:
    """Collapse alternating pairs whose non-empty cells are complementary.

    A row pair (R, R+1) is complementary when both rows have content but no
    column is filled in both. PDFs with shaded zebra rows often cause pdfplumber
    to double the row count this way.
    """
    if len(rows) < 4:
        return rows

    width = len(rows[0])

    def mask(row: list[str]) -> tuple[bool, ...]:
        return tuple(bool(c) for c in row)

    pairs_total = 0
    pairs_complementary = 0
    for i in range(0, len(rows) - 1, 2):
        m1, m2 = mask(rows[i]), mask(rows[i + 1])
        if not any(m1) or not any(m2):
            continue
        pairs_total += 1
        if not any(a and b for a, b in zip(m1, m2)):
            pairs_complementary += 1

    if pairs_total < 2 or pairs_complementary / pairs_total < 0.7:
        return rows

    merged: list[list[str]] = []
    i = 0
    while i < len(rows):
        if i + 1 < len(rows):
            merged.append([rows[i][c] or rows[i + 1][c] for c in range(width)])
            i += 2
        else:
            merged.append(rows[i])
            i += 1
    return merged


def _looks_like_real_table(rows: list[list[str]]) -> bool:
    if len(rows) < 1 + MIN_DATA_ROWS:
        return False
    if not rows[0] or len(rows[0]) < MIN_COLUMNS:
        return False

    non_empty = [c for r in rows for c in r if c]
    if not non_empty:
        return False
    long_cells = sum(1 for c in non_empty if len(c) > 120)
    if long_cells / len(non_empty) > 0.3:
        return False
    return True


def _table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = len(rows[0])
    col_widths = [max(3, max(len(r[c]) for r in rows)) for c in range(width)]

    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(row)) + " |"

    header, *rest = rows
    lines = [fmt(header), "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"]
    lines.extend(fmt(r) for r in rest)
    return "\n".join(lines)


def _clean_table(raw_rows: list[list[Any]]) -> str | None:
    rows = _normalise_rows(raw_rows)
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return None
    rows = _drop_empty_columns(rows)
    if not rows or not rows[0]:
        return None
    rows = _merge_zebra_rows(rows)
    rows = _drop_empty_columns(rows)
    rows = _merge_exclusive_columns(rows)
    rows = _drop_empty_columns(rows)
    if not _looks_like_real_table(rows):
        return None
    return _table_to_markdown(rows)


def _body_font_size(page: Any) -> float:
    """Modal char size on the page — used as the baseline for heading detection."""
    chars = page.chars or []
    if not chars:
        return 0.0
    sizes = Counter(round(c["size"], 1) for c in chars if c.get("size"))
    if not sizes:
        return 0.0
    return float(sizes.most_common(1)[0][0])


def _heading_level(ratio: float) -> int | None:
    """Return a heading level (1-3) for a line whose font is ``ratio`` × body."""
    if ratio >= 1.8:
        return 1
    if ratio >= 1.45:
        return 2
    if ratio >= 1.2:
        return 3
    return None


def _is_heading_worthy(text: str) -> bool:
    """Reject lines that are obviously not section headings even in big fonts.

    Catches page numbers, footnote markers like ``5)`` or ``*``, decorative
    glyphs, and lines with too few real letters to navigate to.
    """
    alpha = sum(1 for c in text if c.isalpha())
    if alpha < 3:
        return False
    if "|" in text:
        return False
    return True


def _format_band(page: Any, top: float, bottom: float, body_size: float) -> str:
    """Extract a vertical slice of the page, promoting larger-font lines to
    Markdown headings based on font-size ratio against ``body_size``.
    """
    if bottom - top < 2:
        return ""
    try:
        cropped = page.crop((0, top, page.width, bottom), strict=False)
    except Exception:
        return ""

    try:
        text_lines = cropped.extract_text_lines(x_tolerance=2, y_tolerance=3)
    except Exception:
        text = cropped.extract_text(x_tolerance=2, y_tolerance=3) or ""
        return text.strip()

    if not text_lines:
        return ""

    out: list[str] = []
    for line in text_lines:
        text = (line.get("text") or "").strip()
        if not text:
            continue

        level: int | None = None
        if body_size > 0 and len(text) <= 120:
            line_chars = line.get("chars") or []
            if line_chars:
                avg = sum(c["size"] for c in line_chars if c.get("size")) / max(
                    1, sum(1 for c in line_chars if c.get("size"))
                )
                if avg:
                    level = _heading_level(avg / body_size)

        if level is not None and _is_heading_worthy(text):
            out.append("")
            out.append(f"{'#' * level} {text}")
            out.append("")
        else:
            out.append(text)

    return "\n".join(out).strip()


def _convert_page(
    page: Any,
    image_markers: list[tuple[float, str]] = (),
) -> str:
    body_size = _body_font_size(page)

    try:
        tables = page.find_tables(TABLE_SETTINGS_STRICT) or []
    except Exception:
        tables = []

    accepted: list[tuple[tuple[float, float, float, float], str]] = []
    for t in tables:
        md = _clean_table(t.extract() or [])
        if md:
            accepted.append((t.bbox, md))

    accepted.sort(key=lambda x: x[0][1])

    if not accepted and not image_markers:
        return _format_band(page, 0.0, float(page.height), body_size)

    # Tables advance the cursor past their bbox (text inside the table is
    # captured by the table itself). Image markers are zero-height anchors
    # at their top-y — text around the image is still extracted from the
    # surrounding bands, since the image lives on top of the text layer.
    # Ties at the same y put tables first so a table's contents aren't
    # split by an image that happens to sit on its border.
    obstacles: list[tuple[float, float, str, bool]] = [
        (bbox[1], bbox[3], md, True) for bbox, md in accepted
    ]
    obstacles.extend(
        (float(y), float(y), placeholder, False)
        for y, placeholder in image_markers
    )
    obstacles.sort(key=lambda o: (o[0], 0 if o[3] else 1))

    chunks: list[tuple[float, str]] = []
    cursor = 0.0
    page_bottom = float(page.height)

    for top, bottom, md, is_table in obstacles:
        if top > cursor:
            band = _format_band(page, cursor, top, body_size)
            if band:
                chunks.append((cursor, band))
        chunks.append((top, md))
        if is_table:
            cursor = bottom
        else:
            # Image marker is zero-height. Advance cursor to its top so the
            # next band starts there — text inside the image's bbox is
            # captured by that next band (the image sits on top of the
            # text layer, not in place of it). Without this, the next band
            # would re-extract everything from the previous cursor and
            # duplicate text we already emitted.
            cursor = max(cursor, top)

    if cursor < page_bottom:
        band = _format_band(page, cursor, page_bottom, body_size)
        if band:
            chunks.append((cursor, band))

    chunks.sort(key=lambda c: c[0])
    return "\n\n".join(c[1] for c in chunks)


class PdfPlumberTableConverter(DocumentConverter):
    """PDF converter that emits proper Markdown tables for ruled tables.

    When ``inline_images`` is ``True``, a comment-style placeholder is
    emitted at every embedded image's on-page y-position so the worker can
    later swap each one for either a file link (extract mode) or a base64
    data URI (embed mode). The placeholders mean images land at their
    original spot in the document rather than in an appendix.
    """

    def __init__(self, *, inline_images: bool = False) -> None:
        self._inline_images = inline_images

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> bool:
        ext = (stream_info.extension or "").lower()
        if ext in ACCEPTED_EXTENSIONS:
            return True
        mime = (stream_info.mimetype or "").lower()
        return any(mime.startswith(p) for p in ACCEPTED_MIME_PREFIXES)

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        raw_bytes = file_stream.read()
        pdf_bytes = io.BytesIO(raw_bytes)

        image_markers_by_page: dict[int, list[tuple[float, str]]] = {}
        if self._inline_images:
            try:
                from .pdf_image_extractor import iter_pdf_image_markers
                image_markers_by_page = iter_pdf_image_markers(raw_bytes)
            except Exception:
                image_markers_by_page = {}

        try:
            page_chunks: list[str] = []
            with pdfplumber.open(pdf_bytes) as pdf:
                for page_index, page in enumerate(pdf.pages):
                    markers = image_markers_by_page.get(page_index, [])
                    try:
                        page_md = _convert_page(page, markers)
                    except Exception:
                        page_md = (page.extract_text() or "").strip()
                    if page_md.strip():
                        page_chunks.append(page_md)
                    page.close()
            markdown = "\n\n".join(page_chunks).strip()
        except Exception:
            pdf_bytes.seek(0)
            markdown = pdfminer.high_level.extract_text(pdf_bytes)

        if not markdown:
            pdf_bytes.seek(0)
            markdown = pdfminer.high_level.extract_text(pdf_bytes)

        return DocumentConverterResult(markdown=markdown)
