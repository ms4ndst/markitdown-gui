"""Tests for the TABLE repair pass in ``app.markdown_cleanup``.

The pass exists to stop PDF-extracted tables (header rows with no delimiter,
stray page-break delimiter rows) from tripping a markdown parser's
nesting-depth guard. These tests pin the parse-critical invariant — every
emitted table has its delimiter row in position 2 — and guard against the
pass churning tables that are already valid.
"""

from __future__ import annotations

import re

from app.markdown_cleanup import apply_lint_fixes, fix_malformed_tables

_SEP = re.compile(r"^\s*\|[\s:\-|]*-[\s:\-|]*\|\s*$")
_ROW = re.compile(r"^\s*\|")


def _delimiter_always_in_row_two(md: str) -> bool:
    """Every contiguous pipe-run has exactly one delimiter, in row 2."""
    lines = md.split("\n")
    i, n = 0, len(lines)
    while i < n:
        if not _ROW.match(lines[i]):
            i += 1
            continue
        j = i
        while j < n and _ROW.match(lines[j]):
            j += 1
        region = lines[i:j]
        if len(region) >= 2:
            seps = [k for k, r in enumerate(region) if _SEP.match(r)]
            if seps != [1]:
                return False
        i = j
    return True


def test_header_without_delimiter_gets_one():
    md = "\n".join(
        [
            "| Field | Type | Comment |",
            "| id    | Str  | the id  |",
            "| name  | Str  | a name  |",
        ]
    )
    fixed, count = fix_malformed_tables(md)
    assert count == 1
    assert _delimiter_always_in_row_two(fixed)
    # Original header and both data rows survive.
    assert "| Field" in fixed and "| id" in fixed and "| name" in fixed


def test_misplaced_delimiter_is_moved_to_row_two():
    md = "\n".join(
        [
            "| Field | Type | Comment |",
            "| id    | Str  | the id  |",
            "|-------|------|---------|",  # delimiter stranded mid-table
            "| name  | Str  | a name  |",
        ]
    )
    fixed, count = fix_malformed_tables(md)
    assert count == 1
    assert _delimiter_always_in_row_two(fixed)
    # No data row was consumed by the relocation.
    for cell in ("id", "name"):
        assert f"| {cell}" in fixed


def test_valid_table_is_left_untouched():
    md = "\n".join(
        [
            "| Field | Type |",
            "| --- | --- |",
            "| id    | Str  |",
            "",
        ]
    )
    fixed, count = fix_malformed_tables(md)
    assert count == 0
    assert fixed == md  # byte-for-byte identical


def test_short_rows_are_padded_to_header_width():
    md = "\n".join(
        [
            "| Field | Type | Comment |",
            "| section: |",  # a 1-cell sub-label row from PDF extraction
            "| id | Str | the id |",
        ]
    )
    fixed, _ = fix_malformed_tables(md)
    assert _delimiter_always_in_row_two(fixed)
    # The padded label row now carries the header's 3 columns.
    label = next(l for l in fixed.split("\n") if l.startswith("| section:"))
    assert label.count("|") == 4  # 3 cells -> 4 pipes


def test_lone_pipe_line_is_not_treated_as_a_table():
    md = "a paragraph\n| not really a table |\nmore text"
    fixed, count = fix_malformed_tables(md)
    assert count == 0
    assert fixed == md


def test_pipe_rows_inside_a_code_fence_are_ignored():
    md = "\n".join(
        [
            "```",
            "| Field | Type |",
            "| id | Str |",  # no delimiter, but it's code — leave it
            "```",
        ]
    )
    fixed, count = fix_malformed_tables(md)
    assert count == 0
    assert fixed == md


def test_repaired_table_is_blank_line_fenced():
    md = "Some intro text\n| Field | Type |\n| id | Str |\nTrailing text"
    fixed, count = fix_malformed_tables(md)
    assert count == 1
    lines = fixed.split("\n")
    header_idx = next(i for i, l in enumerate(lines) if l.startswith("| Field"))
    # Blank line separates the table from the paragraph above it.
    assert lines[header_idx - 1] == ""
    # ...and from the paragraph below it (find the last table row).
    last_row = max(i for i, l in enumerate(lines) if _ROW.match(l))
    assert lines[last_row + 1] == ""


def test_runs_clean_through_full_pipeline():
    md = "\n".join(
        [
            "# Title",
            "| Field | Type | Comment |",
            "| id    | Str  | the id  |",
            "| name  | Str  | a name  |",
        ]
    )
    fixed, counts = apply_lint_fixes(md)
    assert counts.get("TABLE") == 1
    assert _delimiter_always_in_row_two(fixed)
