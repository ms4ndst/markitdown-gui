"""Tests for ``fix_reference_tables`` in ``app.markdown_cleanup`` and the
table-row guard in ``strip_headers_footers``."""

from __future__ import annotations

from app.markdown_cleanup import fix_reference_tables, strip_headers_footers


def _table(*rows: str) -> str:
    return "\n".join(rows)


def test_blank_header_named_for_reference_table():
    md = _table(
        "|      |        |    |           |",
        "|------|--------|----|-----------|",
        "| file | Byte[] |    | Filecontent |",
        "| cid  | String | 8  | Company   |",
    )
    out, changes, _ = fix_reference_tables(md)
    assert changes == 1
    header = [c.strip() for c in out.splitlines()[0].strip("|").split("|")]
    assert header == ["Field", "Datatype", "Size", "Comment"]


def test_blank_header_named_for_enum_table():
    md = _table("|     |     |", "|-----|-----|", "| 0   | not blocked |", "| 1   | blocked |")
    out, _, _ = fix_reference_tables(md)
    assert out.splitlines()[0].startswith("| Value")


def test_datatype_casing_is_canonicalised():
    md = _table(
        "| Field | Datatype | Size | Comment |",
        "|-------|----------|------|---------|",
        "| uac   | int      |      | User Access Code |",
        "| vat   | byte     |      | VAT code |",
    )
    out, changes, warnings = fix_reference_tables(md)
    assert changes == 1 and not warnings
    assert "| Int " in out and "| Byte " in out


def test_size_text_moved_to_comment_and_reported():
    md = _table(
        "| Inputfield | Datatype | Size | Comment |",
        "|------------|----------|------|---------|",
        "| invnumber  | Int      | Invoice log number |  |",
    )
    out, _, warnings = fix_reference_tables(md)
    row = [c.strip() for c in out.splitlines()[2].strip("|").split("|")]
    assert row == ["invnumber", "Int", "", "Invoice log number"]
    assert any("Size to Comment" in w for w in warnings)


def test_unknown_datatype_is_warned_not_changed():
    md = _table(
        "| Field | Datatype | Size | Comment |",
        "|-------|----------|------|---------|",
        "| foramount | Decmal | 28,8 | Foreign amount |",
        "| ledgerType | PersonEnumType | | 1) |",
    )
    out, changes, warnings = fix_reference_tables(md)
    assert changes == 0 and out == md
    assert warnings == ["unknown datatype 'Decmal' for field 'foramount'"]


def test_non_reference_tables_untouched():
    md = _table("| Type | Comment |", "|------|---------|", "| Articles | changes |")
    assert fix_reference_tables(md) == (md, 0, [])


def test_header_footer_strip_keeps_repeated_table_rows():
    row = "| id | String | 20 | Article Id |"
    md = "\n\n".join(
        _table("| Field | Datatype | Size | Comment |", "|---|---|---|---|", row)
        for _ in range(4)
    )
    out, removed = strip_headers_footers(md)
    assert removed == 0 and out.count(row) == 4
