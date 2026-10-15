"""Tests for ``app.pdf_table_converter``.

The fixtures draw ruled tables the way the Control Edge API reference does —
bold header row, a decorative sub-rule inside the header, empty Size cells,
tables cut by a page break — and assert the converter places every cell in
its own column and keeps one header per table.
"""

from __future__ import annotations

import io
import re

import pytest

from app.pdf_table_converter import (
    PdfPlumberTableConverter,
    _Line,
    _render_text,
)

fitz = pytest.importorskip("fitz")
from markitdown import StreamInfo  # noqa: E402

# Column rules of a 4-column reference table, and a decorative sub-rule
# that only the header row carries — it runs through the word "Size".
COLS = [72, 160, 210, 240, 520]
HEADER_SUBRULE = 222
ROW_H = 12


def _draw_table(page, top, rows, *, header=True, subrule=True):
    """Draw ``rows`` (header first when ``header``) as a ruled table."""
    y = top
    for r, cells in enumerate(rows):
        is_head = header and r == 0
        page.draw_line((COLS[0], y), (COLS[-1], y))
        for x in COLS:
            page.draw_line((x, y), (x, y + ROW_H))
        if is_head and subrule:
            page.draw_line((HEADER_SUBRULE, y), (HEADER_SUBRULE, y + ROW_H))
        for c, text in enumerate(cells):
            if text:
                page.insert_text(
                    (COLS[c] + 3, y + ROW_H - 3), text, fontsize=8,
                    fontname="hebo" if (is_head or c == 0) else "helv",
                )
        y += ROW_H
    page.draw_line((COLS[0], y), (COLS[-1], y))
    return y


def _convert(doc) -> str:
    data = doc.tobytes()
    result = PdfPlumberTableConverter().convert(
        io.BytesIO(data), StreamInfo(extension=".pdf")
    )
    return result.markdown


def _table_rows(md: str) -> list[list[str]]:
    return [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in md.splitlines()
        if line.startswith("|") and not re.match(r"^\|[-|]+\|$", line)
    ]


HEADER = ["Inputfield", "Datatype", "Size", "Comment"]


def test_empty_size_cell_stays_in_its_column():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "This method uploads an invoice log attachment", fontsize=11)
    _draw_table(page, 80, [
        HEADER,
        ["invserie", "String", "8", "Invoice log serie"],
        ["invnumber", "Int", "", "Invoice log number"],
        ["file", "Byte[]", "", "Filecontent"],
    ])
    rows = _table_rows(_convert(doc))
    assert rows[0] == HEADER
    assert rows[2] == ["invnumber", "Int", "", "Invoice log number"]
    assert rows[3] == ["file", "Byte[]", "", "Filecontent"]


def test_header_subrule_does_not_split_words():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Intro text", fontsize=11)
    _draw_table(page, 80, [HEADER, ["accountnumber", "String", "6", "Account number"]])
    rows = _table_rows(_convert(doc))
    assert rows[0] == HEADER
    assert all(len(r) == 4 for r in rows)


def test_page_break_continuation_is_appended_not_promoted():
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 60), "Some intro", fontsize=11)
    # Header plus one row at the very bottom of page 1...
    bottom = p1.rect.height - 60 - 2 * ROW_H
    _draw_table(p1, bottom, [HEADER, ["group1", "String", "64", "Free group 1"]])
    # ...and the headerless rest at the top of page 2, without the sub-rule.
    p2 = doc.new_page()
    _draw_table(p2, 60, [
        ["group2", "String", "64", "Free group 2"],
        ["language", "String", "8", "Language code"],
    ], header=False)
    md = _convert(doc)
    rows = _table_rows(md)
    assert rows[0] == HEADER
    assert [r[0] for r in rows[1:]] == ["group1", "group2", "language"]
    delimiters = [l for l in md.splitlines() if re.match(r"^\|[-|]+\|$", l)]
    assert len(delimiters) == 1  # one table, one delimiter row


def test_headerless_table_gets_blank_header_not_data_row():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "1)", fontsize=11)
    page.insert_text((72, 300), "Trailing text keeps the table off the page edge", fontsize=11)
    _draw_table(page, 120, [
        ["0", "", "", "invoicing is performed afterwards"],
        ["1", "", "", "invoicing is performed in advance"],
    ], header=False)
    rows = _table_rows(_convert(doc))
    assert rows[0] == ["", ""]
    assert rows[1] == ["0", "invoicing is performed afterwards"]


def _lines(*specs):
    """``(text, top, size)`` triples -> ``_Line`` objects 2pt shorter than
    the line pitch the caller chose."""
    return [_Line(t, top, top + size, size) for t, top, size in specs]


def test_method_line_is_h2_and_description_h3_whatever_the_font():
    md = _render_text(_lines(
        ("Patch method : /api/cashflow/{id}", 100, 11),
        ("This method updates a cashflow item.", 130, 11),
    ), body=11)
    assert md.splitlines()[0] == "## Patch method : /api/cashflow/{id}"
    assert "### This method updates a cashflow item." in md


def test_wrapped_description_becomes_one_heading():
    md = _render_text(_lines(
        ("Post method : /api/ledger/create-supplier-ledger", 70, 12),
        ("Creates a supplier ledger, creates period", 100, 11),
        ("allocations for rows. For changing", 114, 11),
        ("an existing ledger Invno must be greater than 0.", 128, 11),
        ("Example of calculation of amounts:", 160, 11),
    ), body=11)
    headings = [l for l in md.splitlines() if l.startswith("###")]
    assert headings == [
        "### Creates a supplier ledger, creates period allocations for rows. "
        "For changing an existing ledger Invno must be greater than 0."
    ]
    assert "\nExample of calculation of amounts:" in md


def test_wrapped_prose_is_joined_and_paragraphs_kept_apart():
    md = _render_text(_lines(
        ("Using the API, you can easily create integrations between", 100, 10),
        ("accounting applications and BI systems.", 112, 10),
        ("A second paragraph.", 140, 10),
    ), body=10)
    assert md == (
        "Using the API, you can easily create integrations between "
        "accounting applications and BI systems.\n\nA second paragraph."
    )


def test_toc_lines_are_never_headings_or_joined():
    md = _render_text(_lines(
        ("Get method : /api/account/get-accounts ........ 13", 100, 11),
        ("Get method : /api/account/get-by-id ........ 15", 112, 11),
    ), body=11)
    assert not md.startswith("#")
    assert len([l for l in md.splitlines() if l]) == 2
