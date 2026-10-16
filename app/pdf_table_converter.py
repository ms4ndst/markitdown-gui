"""Table-aware PDF -> Markdown converter using pdfplumber.

Strategy
--------
1. Detect tables with ``vertical_strategy="lines"`` and
   ``horizontal_strategy="lines"`` only — never trust text alignment, which
   produces phantom columns on PDFs with zebra-striped row backgrounds.
2. Build every table's cells *by position*, not by pdfplumber's per-cell
   text extraction (see ``_positional_table``):
   * the true column separators are the ruling edges every multi-cell row
     shares, minus any edge that cuts through a word — decorative sub-rules
     inside a header row are not columns,
   * each whole word is placed in the column containing its horizontal
     centre, so a word is never cut in two (``D | atatype``) and a column
     with no text stays an empty cell instead of letting the text to its
     right slide left into it.
3. A row whose every glyph is bold is the table's header. A table without
   one (a page-break continuation, or a table the source never gave a
   header) is emitted with a blank header row — a data row is never
   promoted to header position.
4. A table cut off by a page break is reunited with its headerless
   continuation on the next page when both share the same column grid.
5. Text outside tables is rendered after all pages are parsed, so heading
   levels come from one document-wide body font size instead of each page's
   own mix of fonts. Wrapped heading and paragraph lines are joined.
6. If detection fails, fall back to plain pdfminer text for the whole
   document — never silently emit a broken table.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Union

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

# Two ruling edges closer than this (points) are the same edge.
_EDGE_TOL = 1.5

# A table whose bbox sits within this many points of the page's top or
# bottom edge is treated as a possible page-break continuation. Generous
# enough to cover typical page margins without letting a table that merely
# happens to be first/last on an otherwise text-heavy page qualify.
_EDGE_TOLERANCE = 100.0

# "Get method : /api/..." — an endpoint title in API reference documents.
# Always an H2, whatever font the PDF gives it, and the paragraph right after
# it (the endpoint description) is its H3.
_METHOD_RE = re.compile(r"^(Get|Post|Put|Patch|Delete) method ?: ?/api/", re.IGNORECASE)
# Dot-leader table-of-contents entry: never a heading, never joined.
_TOC_LINE_RE = re.compile(r"(?:\.\s*){4,}\d{1,6}\s*$")
_LIST_START_RE = re.compile(r"^\s*(?:\d+[.)]|[-*+•‣◦▪●○])\s")
_BOLD_RE = re.compile(r"bold|black|heavy|semibold", re.IGNORECASE)
# A sentence ending followed by another sentence: "Notera. Inställning …".
# Two letters before the stop, so "1. Inledning" / "Kap. 3" don't count.
_SENTENCE_BREAK_RE = re.compile(r"[^\W\d_]{2}[.!?]\s+[A-ZÅÄÖ]")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text.replace("|", "\\|")


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


@dataclass
class _Table:
    """A table under assembly. ``rows`` keeps every positional column (empty
    ones included) until rendering, so a page-break continuation can be
    appended column-for-column."""

    rows: list[list[str]]
    bounds: tuple[float, ...]
    has_header: bool


def _shared_edges(edge_sets: list[list[float]]) -> list[float]:
    """Edges present (within ``_EDGE_TOL``) in every one of ``edge_sets``."""
    shared: list[float] = []
    for x in sorted(edge_sets[0]):  # a cell's x1 is its neighbour's x0
        if not shared or x - shared[-1] > _EDGE_TOL:
            shared.append(x)
    for edges in edge_sets[1:]:
        shared = [x for x in shared if any(abs(x - y) <= _EDGE_TOL for y in edges)]
    return shared


def _positional_table(page: Any, table: Any) -> _Table | None:
    """Rebuild ``table`` from word positions.

    pdfplumber derives its cell grid from every ruling line, including
    decorative sub-rules drawn only inside a header row, and reports a cell
    spanning several grid columns as text in the first one plus ``None``s.
    Indexing that grid by position puts an empty cell's neighbour into it;
    cutting text at each grid line splits words that a sub-rule crosses.
    Assigning whole words to real columns by x-position avoids both.
    """
    try:
        rows = table.rows
    except Exception:
        return None
    if not rows:
        return None

    edge_sets: list[list[float]] = []
    for row in rows:
        cells = [c for c in row.cells if c is not None]
        if len(cells) >= 2:
            edge_sets.append([x for c in cells for x in (c[0], c[2])])
    if not edge_sets:
        return None
    seps = _shared_edges(edge_sets)
    if len(seps) < 3:  # fewer than two columns
        return None

    x0, top, x1, bottom = table.bbox
    try:
        words = page.crop((x0, top, x1, bottom), strict=False).extract_words(
            x_tolerance=3, y_tolerance=3, extra_attrs=["fontname", "non_stroking_color"]
        )
    except Exception:
        return None

    # An edge that runs through a word is a decorative rule, not a column
    # boundary — it would otherwise cut "Size" into "S" | "ize".
    inner = [
        s for s in seps[1:-1]
        if not any(w["x0"] < s - 1 and w["x1"] > s + 1 for w in words)
    ]
    seps = [seps[0], *inner, seps[-1]]
    n_cols = len(seps) - 1
    if n_cols < MIN_COLUMNS:
        return None

    def col_of(xc: float) -> int:
        for c in range(n_cols):
            if xc < seps[c + 1]:
                return c
        return n_cols - 1

    row_bands = sorted({(round(r.bbox[1], 1), round(r.bbox[3], 1)) for r in rows})
    grid: list[list[list[dict]]] = [[[] for _ in range(n_cols)] for _ in row_bands]
    bold_flags: list[list[bool]] = [[] for _ in row_bands]
    colors: list[list[str]] = [[] for _ in row_bands]
    for w in words:
        yc = (w["top"] + w["bottom"]) / 2
        r = next((i for i, (t, b) in enumerate(row_bands) if t <= yc < b), None)
        if r is None:
            continue
        grid[r][col_of((w["x0"] + w["x1"]) / 2)].append(w)
        bold_flags[r].append(bool(_BOLD_RE.search(w.get("fontname") or "")))
        colors[r].append(str(w.get("non_stroking_color")))

    def cell_text(ws: list[dict]) -> str:
        ws = sorted(ws, key=lambda w: (round(w["top"]), w["x0"]))
        return _cell(" ".join(w["text"] for w in ws))

    out_rows: list[list[str]] = []
    out_bold: list[list[bool]] = []
    out_colors: list[list[str]] = []
    for r, cols in enumerate(grid):
        row = [cell_text(ws) for ws in cols]
        if any(row):
            out_rows.append(row)
            out_bold.append(bold_flags[r])
            out_colors.append(colors[r])
    if not out_rows:
        return None

    any_bold = any(any(f) for f in out_bold)
    first_filled = sum(1 for c in out_rows[0] if c)
    body_colors = Counter(c for cs in out_colors[1:] for c in cs)
    head_colors = set(out_colors[0])
    # Header text drawn in its own colour (white on a filled band) marks the
    # header even when the font isn't bold.
    colored_head = (
        len(head_colors) == 1
        and bool(body_colors)
        and next(iter(head_colors)) != body_colors.most_common(1)[0][0]
    )
    if any_bold or colored_head:
        # Data rows in reference tables often bold their first column, so
        # only a row that is bold throughout counts as a header.
        has_header = (all(out_bold[0]) or colored_head) and first_filled >= 2
    else:
        # No font cue at all: keep the conventional first-row-is-header.
        has_header = first_filled >= 2

    return _Table(out_rows, tuple(seps), has_header)


def _continuation_map(prev: _Table, cont: _Table, tol: float = 3.0) -> list[int] | None:
    """Map each of ``cont``'s columns onto ``prev``'s, or ``None`` when
    ``cont`` does not continue ``prev``.

    The two fragments of a page-split table rarely share an identical grid:
    a fragment holding only the header row carries the header's decorative
    sub-rules, the other fragment only the real column rules. So the outer
    edges must match, and every column of ``cont`` that holds text must land
    — by its centre — in a distinct column of ``prev``, in the same order.
    """
    a, b = prev.bounds, cont.bounds
    if abs(a[0] - b[0]) > tol or abs(a[-1] - b[-1]) > tol:
        return None

    def col_of(x: float) -> int:
        for c in range(len(a) - 1):
            if x < a[c + 1]:
                return c
        return len(a) - 2

    mapping = [col_of((b[c] + b[c + 1]) / 2) for c in range(len(b) - 1)]
    filled = [mapping[c] for c in range(len(b) - 1) if any(r[c] for r in cont.rows)]
    if any(x >= y for x, y in zip(filled, filled[1:])):
        return None
    return mapping


def _append_rows(prev: _Table, cont: _Table, mapping: list[int]) -> None:
    for row in cont.rows:
        new = [""] * (len(prev.bounds) - 1)
        for c, text in enumerate(row):
            if text:
                new[mapping[c]] = f"{new[mapping[c]]} {text}".strip()
        prev.rows.append(new)


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


def _looks_like_real_table(t: _Table) -> bool:
    """Reject bordered text boxes: one real column, or mostly long prose."""
    filled_cols = sum(1 for c in range(len(t.bounds) - 1) if any(r[c] for r in t.rows))
    if filled_cols < MIN_COLUMNS:
        return False
    non_empty = [c for r in t.rows for c in r if c]
    long_cells = sum(1 for c in non_empty if len(c) > 120)
    return long_cells / len(non_empty) <= 0.3


def _render_table(t: _Table) -> str:
    rows = t.rows
    if t.has_header:
        header, body = rows[0], rows[1:]
    else:
        header, body = [""] * len(rows[0]), rows
    body = _merge_zebra_rows(body) if body else body
    all_rows = [header, *body]
    keep = [c for c in range(len(header)) if any(r[c] for r in all_rows)]
    all_rows = [[r[c] for c in keep] for r in all_rows]
    widths = [max(3, max(len(r[c]) for r in all_rows)) for c in range(len(keep))]

    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(row)) + " |"

    lines = [fmt(all_rows[0]), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    lines.extend(fmt(r) for r in all_rows[1:])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------


@dataclass
class _Line:
    text: str
    top: float
    bottom: float
    size: float


@dataclass
class _TextBlock:
    lines: list[_Line] = field(default_factory=list)


_Item = Union[_TextBlock, _Table, str]  # str = image placeholder


def _band_lines(page: Any, top: float, bottom: float) -> list[_Line]:
    if bottom - top < 2:
        return []
    try:
        cropped = page.crop((0, top, page.width, bottom), strict=False)
        raw = cropped.extract_text_lines(x_tolerance=2, y_tolerance=3)
    except Exception:
        return []
    out: list[_Line] = []
    for line in raw:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        sizes = [c["size"] for c in (line.get("chars") or []) if c.get("size")]
        size = sum(sizes) / len(sizes) if sizes else 0.0
        out.append(_Line(text, float(line["top"]), float(line["bottom"]), size))
    return out


def _is_heading_worthy(text: str) -> bool:
    """Reject lines that are obviously not section headings even in big fonts.

    Catches page numbers, footnote markers like ``5)`` or ``*``, decorative
    glyphs, and lines with too few real letters to navigate to.
    """
    alpha = sum(1 for c in text if c.isalpha())
    if alpha < 3:
        return False
    if "|" in text or _TOC_LINE_RE.search(text):
        return False
    # A bullet ("● Kan nu erbjuda …") is a list item even when the slide or
    # page sets it in a large font.
    if _LIST_START_RE.match(text):
        return False
    return True


def _is_footer_noise(text: str) -> bool:
    """True for a bare page number or other decorative running header/footer
    line. Used to look past such boilerplate when deciding whether an
    edge-touching table is truly the first/last meaningful content on the
    page: a page number sitting next to a table that was cut off by the page
    break must not stop it from being recognized as a continuation.
    """
    stripped = text.strip()
    if not stripped:
        return True
    return sum(1 for c in stripped if c.isalpha()) < 3


def _heading_level(size: float, body: float) -> int | None:
    """Heading level for a line ``size`` points tall, against the document's
    body size. Two size tiers only: document titles (H1) and section /
    endpoint titles (H2); H3 is reserved for the endpoint description rule
    in :func:`_render_text`, which no font size can express reliably."""
    if body <= 0 or size <= 0:
        return None
    ratio = size / body
    if ratio >= 1.6:
        return 1
    if ratio >= 1.05:
        return 2
    return None


def _render_text(lines: list[_Line], body: float) -> str:
    """Render one band of text lines: assign heading levels, then join lines
    that wrapped — consecutive lines of the same kind with only line spacing
    between them form one heading or one paragraph."""
    blocks: list[list[Any]] = []  # [level or 0, text, last_line]
    # Endpoint description: the paragraph right after a method title.
    # "expect" = the next line starts it; "inside" = wrapped lines join it.
    desc = "none"
    for ln in lines:
        text = ln.text
        prev = blocks[-1] if blocks else None
        gap = ln.top - prev[2].bottom if prev else None
        tight = gap is not None and gap <= 0.45 * max(ln.size, prev[2].size, 1.0)
        is_method = bool(_METHOD_RE.match(text)) and not _TOC_LINE_RE.search(text)
        unjoinable = (
            prev is None
            or bool(_TOC_LINE_RE.search(text) or _TOC_LINE_RE.search(prev[1]))
            or _is_footer_noise(text)
            or _is_footer_noise(prev[1])
            or bool(_LIST_START_RE.match(text))
            or is_method
        )

        if is_method:
            blocks.append([2, text, ln])
            desc = "expect"
            continue
        if desc == "expect" and ln.size <= body * 1.04 and not _is_footer_noise(text):
            blocks.append([3, text, ln])
            desc = "inside"
            continue
        if desc == "inside" and tight and not unjoinable:
            prev[1] = f"{prev[1]} {text}"
            prev[2] = ln
            continue
        desc = "none"

        # The wrapped tail of a bullet ("● Beställning … görs" / "direkt
        # mellan kund och Inexchange") belongs to that bullet, whatever its
        # font size — otherwise a big-font slide bullet's second line would
        # become a heading.
        if (
            prev is not None
            and prev[0] == 0
            and tight
            and _LIST_START_RE.match(prev[1])
            and not unjoinable
        ):
            prev[1] = f"{prev[1]} {text}"
            prev[2] = ln
            continue

        level = None
        if len(text) <= 120 and _is_heading_worthy(text):
            level = _heading_level(ln.size, body)
        lvl = level or 0
        # Wrapped lines: same kind, only line spacing between them. A heading
        # line starting in lowercase continues the heading above it, and
        # stacked title lines (title + version on a cover page) are one H1.
        if (
            not unjoinable
            and prev[0] == lvl
            and lvl != 3
            and (tight or (lvl and text[:1].islower()) or lvl == 1)
        ):
            prev[1] = f"{prev[1]} {text}"
            prev[2] = ln
        else:
            blocks.append([lvl, text, ln])

    out: list[str] = []
    for lvl, text, _ in blocks:
        # Joined big-font lines can add up to a paragraph (slides often set
        # body text large): too long, or several sentences, is not a title.
        if lvl and lvl != 3 and (
            len(text) > 120 or _SENTENCE_BREAK_RE.search(text)
        ):
            lvl = 0
        out.append(f"{'#' * lvl} {text}" if lvl else text)
    return "\n\n".join(out).strip()


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------


@dataclass
class _Page:
    items: list[_Item]
    leading: _Table | None
    trailing: _Table | None


def _parse_page(
    page: Any,
    image_markers: list[tuple[float, str]] = (),
    furniture: frozenset[str] = frozenset(),
) -> _Page:
    """Split one page into vertically ordered text blocks, tables and image
    placeholders, and note a table touching the page's top or bottom edge —
    a candidate to be joined with its neighbour across the page break.

    ``furniture`` holds image placeholders that repeat on many pages (a logo
    in the footer); like a page number, they never count as the content
    that separates a table from the page edge."""
    try:
        found = page.find_tables(TABLE_SETTINGS_STRICT) or []
    except Exception:
        found = []

    page_bottom = float(page.height)
    tables: list[tuple[tuple[float, float, float, float], _Table]] = []
    for t in found:
        pt = _positional_table(page, t)
        if pt is not None and _looks_like_real_table(pt):
            tables.append((t.bbox, pt))
    tables.sort(key=lambda x: x[0][1])

    # Tables advance the cursor past their bbox (text inside the table is
    # captured by the table itself). Image markers are zero-height anchors
    # at their top-y — text around the image is still extracted from the
    # surrounding bands, since the image lives on top of the text layer.
    # Ties at the same y put tables first so a table's contents aren't
    # split by an image that happens to sit on its border.
    obstacles: list[tuple[float, float, _Item]] = [(b[1], b[3], t) for b, t in tables]
    obstacles.extend((float(y), float(y), ph) for y, ph in image_markers)
    obstacles.sort(key=lambda o: (o[0], 0 if isinstance(o[2], _Table) else 1))

    items: list[tuple[float, _Item]] = []
    cursor = 0.0
    for top, bottom, obj in obstacles:
        if top > cursor:
            lines = _band_lines(page, cursor, top)
            if lines:
                items.append((cursor, _TextBlock(lines)))
        items.append((top, obj))
        cursor = bottom if isinstance(obj, _Table) else max(cursor, top)
    if cursor < page_bottom:
        lines = _band_lines(page, cursor, page_bottom)
        if lines:
            items.append((cursor, _TextBlock(lines)))
    items.sort(key=lambda it: it[0])

    def meaningful(item: _Item) -> bool:
        if isinstance(item, _TextBlock):
            return not all(_is_footer_noise(ln.text) for ln in item.lines)
        if isinstance(item, str):
            return item not in furniture
        return True

    bbox_of = {id(t): b for b, t in tables}
    leading = trailing = None
    first = next((it for _, it in items if meaningful(it)), None)
    last = next((it for _, it in reversed(items) if meaningful(it)), None)
    if isinstance(first, _Table) and bbox_of[id(first)][1] <= _EDGE_TOLERANCE:
        leading = first
    if isinstance(last, _Table) and page_bottom - bbox_of[id(last)][3] <= _EDGE_TOLERANCE:
        trailing = last

    return _Page([it for _, it in items], leading, trailing)


def _body_font_size(pages: list[_Page]) -> float:
    """Modal font size, weighted by characters, of all text outside tables."""
    sizes: Counter[float] = Counter()
    for p in pages:
        for item in p.items:
            if isinstance(item, _TextBlock):
                for ln in item.lines:
                    if ln.size:
                        sizes[round(ln.size, 1)] += len(ln.text)
    return float(sizes.most_common(1)[0][0]) if sizes else 0.0


def _join_page_breaks(pages: list[_Page]) -> None:
    """Append each headerless continuation table to the table it continues on
    the previous page, removing it from its own page. Runs in place."""
    pending: _Table | None = None
    for p in pages:
        lead = p.leading
        mapping = (
            _continuation_map(pending, lead)
            if pending is not None and lead is not None and not lead.has_header
            else None
        )
        if mapping is not None:
            _append_rows(pending, lead, mapping)
            p.items = [it for it in p.items if it is not lead]
            pending = pending if p.trailing is lead else p.trailing
        else:
            pending = p.trailing


def _render_pages(pages: list[_Page]) -> str:
    body = _body_font_size(pages)
    chunks: list[str] = []
    for p in pages:
        for item in p.items:
            if isinstance(item, _Table):
                chunks.append(_render_table(item))
            elif isinstance(item, _TextBlock):
                text = _render_text(item.lines, body)
                if text:
                    chunks.append(text)
            elif item and item.strip():
                chunks.append(item)
    return "\n\n".join(chunks).strip()


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

        # An image placed on three or more pages is page furniture (a logo).
        pages_per_marker = Counter(
            ph for markers in image_markers_by_page.values() for ph in {p for _, p in markers}
        )
        furniture = frozenset(ph for ph, n in pages_per_marker.items() if n >= 3)

        try:
            pages: list[_Page] = []
            with pdfplumber.open(pdf_bytes) as pdf:
                for page_index, page in enumerate(pdf.pages):
                    markers = image_markers_by_page.get(page_index, [])
                    try:
                        pages.append(_parse_page(page, markers, furniture))
                    except Exception:
                        text = (page.extract_text() or "").strip()
                        lines = [_Line(t, 0.0, 0.0, 0.0) for t in text.splitlines() if t.strip()]
                        pages.append(_Page([_TextBlock(lines)] if lines else [], None, None))
                    page.close()
            _join_page_breaks(pages)
            markdown = _render_pages(pages)
        except Exception:
            pdf_bytes.seek(0)
            markdown = pdfminer.high_level.extract_text(pdf_bytes)

        if not markdown:
            pdf_bytes.seek(0)
            markdown = pdfminer.high_level.extract_text(pdf_bytes)

        return DocumentConverterResult(markdown=markdown)
