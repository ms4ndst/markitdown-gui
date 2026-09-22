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
5. A wide/tall table that gets cut off by a page break is reunited with its
   continuation on the next page (see ``_bounds_match`` / the merge loop in
   ``PdfPlumberTableConverter.convert``) instead of being emitted as two
   separate, truncated-looking tables — or, worse, silently dropped when the
   continuation alone fails the "looks like a real table" heuristics.
"""

from __future__ import annotations

import io
from collections import Counter
from typing import Any, BinaryIO, NamedTuple

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


def _looks_like_real_table(rows: list[list[str]], *, min_data_rows: int = MIN_DATA_ROWS) -> bool:
    if len(rows) < 1 + min_data_rows:
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


class TableEdge(NamedTuple):
    """A table touching the very top or bottom of a page — a candidate to be
    reunited with its continuation on the adjacent page."""

    raw_rows: list[list[Any]]
    col_bounds: tuple[float, ...] | None


def _column_bounds(t: Any) -> tuple[float, ...] | None:
    """Left-edge x-position of every column, read from the table's own ruling
    lines via its first row's cells. Two tables sharing the same column grid
    are strong evidence they are the same source table split by a page break
    — pdfplumber places both at identical x-coordinates since it derives them
    from the PDF's ruling lines, which repeat unchanged across pages for a
    single continued table.
    """
    try:
        rows = t.rows
    except Exception:
        return None
    if not rows:
        return None
    cells = rows[0].cells
    bounds = [c[0] for c in cells if c is not None]
    if len(bounds) < 2:
        return None
    return tuple(round(b, 1) for b in bounds)


def _bounds_match(a: tuple[float, ...] | None, b: tuple[float, ...] | None, tol: float = 3.0) -> bool:
    if a is None or b is None or len(a) != len(b):
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _starts_with_header_row(rows: list[list[Any]], header_row: list[Any] | None) -> bool:
    """True when ``rows``' first row is identical to ``header_row``.

    Used to *veto* a page-break merge, not to trust it: a genuine
    continuation resumes with data, not a repeat of the header (documents in
    the wild that reuse the same generic column template — "Field / Type /
    Size / Comment" and the like — across many unrelated tables are common,
    and on such a document, two distinct tables landing back-to-back across a
    page break would otherwise look identical to one split table). A leading
    fragment that opens with the exact header text is far more likely a new,
    unrelated table that happens to share the template than a continuation
    that repeats its header — so this blocks the merge rather than stripping
    the row and proceeding.
    """
    if not rows or not header_row:
        return False
    return [_cell(c) for c in rows[0]] == [_cell(c) for c in header_row]


def _clean_table(raw_rows: list[list[Any]], *, min_data_rows: int = MIN_DATA_ROWS) -> str | None:
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
    if not _looks_like_real_table(rows, min_data_rows=min_data_rows):
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


# A table whose bbox sits within this many points of the page's top or
# bottom edge is treated as a possible page-break continuation. Generous
# enough to cover typical page margins without letting a table that merely
# happens to be first/last on an otherwise text-heavy page qualify.
_EDGE_TOLERANCE = 100.0


def _convert_page_parts(
    page: Any,
    image_markers: list[tuple[float, str]] = (),
) -> tuple[list[str], TableEdge | None, TableEdge | None]:
    """Render one page into an ordered list of markdown chunks, plus — when
    applicable — the raw rows of a table touching the page's top or bottom
    edge, so the caller can try to reunite it with its continuation on the
    adjacent page before finalizing the markdown.

    ``leading`` is only set when the topmost chunk on the page is a table
    close to the top edge — i.e. nothing (no heading, no paragraph) precedes
    it, which is exactly the shape a page-break-interrupted table takes on
    the page where it resumes. ``trailing`` mirrors this for the bottom edge.
    A table that is both (it fills the whole page) gets both.
    """
    body_size = _body_font_size(page)

    try:
        tables = page.find_tables(TABLE_SETTINGS_STRICT) or []
    except Exception:
        tables = []

    page_bottom = float(page.height)

    # Raw (pre-clean) rows for every detected table, sorted by top position.
    # A short leftover fragment — just the last row or two of a table cut off
    # by the page break, or just its header with the data starting on the
    # next page — routinely fails `_looks_like_real_table`'s row-count floor
    # on its own. Checked here, before any filtering, so such a fragment is
    # never invisible to the edge/merge detection below purely because it
    # looked too small to stand alone.
    raw_tables: list[tuple[tuple[float, float, float, float], list[list[Any]], tuple[float, ...] | None]] = []
    for t in tables:
        raw_rows = t.extract() or []
        if raw_rows:
            raw_tables.append((t.bbox, raw_rows, _column_bounds(t)))
    raw_tables.sort(key=lambda x: x[0][1])

    # Index of the topmost / bottommost raw table, but only when it actually
    # sits at the page edge — this is what makes it a page-break-continuation
    # candidate rather than just an ordinary table that happens to be first
    # or last among several on an otherwise normal page.
    edge_leading_idx = 0 if raw_tables and raw_tables[0][0][1] <= _EDGE_TOLERANCE else None
    edge_trailing_idx = (
        len(raw_tables) - 1
        if raw_tables and page_bottom - raw_tables[-1][0][3] <= _EDGE_TOLERANCE
        else None
    )

    accepted: list[tuple[tuple[float, float, float, float], str, list[list[Any]], tuple[float, ...] | None, int]] = []
    for i, (bbox, raw_rows, cols) in enumerate(raw_tables):
        md = _clean_table(raw_rows)
        if md is None and i in (edge_leading_idx, edge_trailing_idx):
            # Relax only the row-count floor — a fragment this small is only
            # trusted here because pdfplumber's ruling-line detection already
            # vouches for it being a real table, and it sits exactly where a
            # split table's edge would. The long-cell-ratio guard still
            # applies, so a genuinely non-tabular bordered box at the page
            # edge is not swept in by this.
            md = _clean_table(raw_rows, min_data_rows=0)
        if md:
            accepted.append((bbox, md, raw_rows, cols, i))

    if not accepted and not image_markers:
        band = _format_band(page, 0.0, float(page.height), body_size)
        return ([band] if band else []), None, None

    # Tables advance the cursor past their bbox (text inside the table is
    # captured by the table itself). Image markers are zero-height anchors
    # at their top-y — text around the image is still extracted from the
    # surrounding bands, since the image lives on top of the text layer.
    # Ties at the same y put tables first so a table's contents aren't
    # split by an image that happens to sit on its border.
    obstacles: list[tuple[float, float, str, bool, int]] = [
        (bbox[1], bbox[3], md, True, i) for i, (bbox, md, _raw, _cols, _raw_idx) in enumerate(accepted)
    ]
    obstacles.extend(
        (float(y), float(y), placeholder, False, -1)
        for y, placeholder in image_markers
    )
    obstacles.sort(key=lambda o: (o[0], 0 if o[3] else 1))

    chunks: list[tuple[float, str, int]] = []
    cursor = 0.0

    for top, bottom, md, is_table, idx in obstacles:
        if top > cursor:
            band = _format_band(page, cursor, top, body_size)
            if band:
                chunks.append((cursor, band, -1))
        chunks.append((top, md, idx if is_table else -1))
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
            chunks.append((cursor, band, -1))

    chunks.sort(key=lambda c: c[0])

    leading: TableEdge | None = None
    trailing: TableEdge | None = None
    if chunks:
        _, _text, first_idx = chunks[0]
        if first_idx >= 0 and accepted[first_idx][4] == edge_leading_idx:
            _bbox, _md, raw_rows, cols, _raw_idx = accepted[first_idx]
            leading = TableEdge(raw_rows, cols)
        _, _text, last_idx = chunks[-1]
        if last_idx >= 0 and accepted[last_idx][4] == edge_trailing_idx:
            _bbox, _md, raw_rows, cols, _raw_idx = accepted[last_idx]
            trailing = TableEdge(raw_rows, cols)

    return [c[1] for c in chunks], leading, trailing


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
            page_chunk_lists: list[list[str]] = []
            pending_rows: list[list[Any]] | None = None
            pending_bounds: tuple[float, ...] | None = None
            with pdfplumber.open(pdf_bytes) as pdf:
                for page_index, page in enumerate(pdf.pages):
                    markers = image_markers_by_page.get(page_index, [])
                    try:
                        chunks, leading, trailing = _convert_page_parts(page, markers)
                    except Exception:
                        text = (page.extract_text() or "").strip()
                        chunks, leading, trailing = ([text] if text else []), None, None

                    carried_forward = False
                    if (
                        pending_rows is not None
                        and leading is not None
                        and _bounds_match(pending_bounds, leading.col_bounds)
                        and not _starts_with_header_row(
                            leading.raw_rows, pending_rows[0] if pending_rows else None
                        )
                    ):
                        combined_rows = pending_rows + leading.raw_rows
                        merged_md = _clean_table(combined_rows)
                        if merged_md:
                            if page_chunk_lists and page_chunk_lists[-1]:
                                page_chunk_lists[-1][-1] = merged_md
                            chunks = chunks[1:]
                            # The continuation may itself run to the bottom of this
                            # page (a table spanning 3+ pages) — carry the combined
                            # rows forward so the next page can extend it further,
                            # instead of treating this page's distinct-looking
                            # trailing table as the start of a new pending table.
                            if trailing is not None and leading.raw_rows is trailing.raw_rows:
                                pending_rows, pending_bounds = combined_rows, leading.col_bounds
                                carried_forward = True

                    if not carried_forward:
                        if trailing is not None:
                            pending_rows, pending_bounds = trailing.raw_rows, trailing.col_bounds
                        else:
                            pending_rows, pending_bounds = None, None

                    page_chunk_lists.append([c for c in chunks if c and c.strip()])
                    page.close()
            page_chunks = ["\n\n".join(cl) for cl in page_chunk_lists if cl]
            markdown = "\n\n".join(page_chunks).strip()
        except Exception:
            pdf_bytes.seek(0)
            markdown = pdfminer.high_level.extract_text(pdf_bytes)

        if not markdown:
            pdf_bytes.seek(0)
            markdown = pdfminer.high_level.extract_text(pdf_bytes)

        return DocumentConverterResult(markdown=markdown)
