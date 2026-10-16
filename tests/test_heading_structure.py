"""Tests for heading-structure fixes: one H1 and no skipped levels, Word
Title style as the H1, bookmark links pointed at headings, and the PDF
heading / contents-page heuristics behind the remaining export errors."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.docx_converter import heading_bookmarks, relink_bookmarks
from app.markdown_cleanup import (
    fix_numbered_section_headings,
    normalize_heading_structure,
    strip_table_of_contents,
)
from app.pdf_table_converter import _Line, _render_text
from app.worker import ConversionItem, ConversionWorker


def _levels(md: str) -> list[int]:
    fence = False
    out = []
    for line in md.split("\n"):
        if line.startswith("```"):
            fence = not fence
        elif not fence and (m := re.match(r"^(#{1,6}) ", line)):
            out.append(len(m.group(1)))
    return out


# --- normalize_heading_structure ---------------------------------------------


def test_skipped_levels_are_closed_up_keeping_siblings():
    md = "# T\n\n### A\n\n#### A1\n\n### B\n\n## C\n\n### C1\n"
    out, changed = normalize_heading_structure(md, "Doc")
    assert _levels(out) == [1, 2, 3, 2, 2, 3]
    assert changed == 3


def test_several_h1s_get_the_document_name_as_title():
    md = "Intro.\n\n# Chapter 1\n\n### Detail\n\n# Chapter 2\n\n## Part\n"
    out, _ = normalize_heading_structure(md, "Invoice Manager")
    assert out.startswith("# Invoice Manager\n\n")
    assert _levels(out) == [1, 2, 3, 2, 3]


def test_clean_structure_is_untouched_and_code_is_ignored():
    md = "# T\n\n## A\n\n```\n#### not a heading\n```\n\n### B\n"
    assert normalize_heading_structure(md, "Doc") == (md, 0)


def test_heading_text_is_preserved():
    out, _ = normalize_heading_structure("# T\n\n### **Bold** title\n", "Doc")
    assert "## **Bold** title" in out


# --- numbered-section promotion ------------------------------------------------


def test_dates_are_not_section_numbers():
    md = "2025.12.01 8\n\n2024.09.1 22\n\n3.6 Sekretess\n"
    out, count = fix_numbered_section_headings(md)
    assert count == 1
    assert "2025.12.01 8" in out.split("\n") and "### 3.6 Sekretess" in out


# --- leader-less PDF contents page -------------------------------------------


def test_leaderless_contents_page_is_removed():
    md = "\n".join([
        "# Sammanfattning",
        "",
        "2026-08-17 4",
        "",
        "Control Edge 4 Integration Amili 4 Notifieringar Tasks 4",
        "",
        "2025.12.01 8",
        "",
        "Control Edge 8 Autogiro 8 Invoice Manager 9",
        "",
        "2026-08-17",
        "",
        "## Control Edge",
        "",
        "## Integration Amili",
        "",
        "Text.",
        "",
        "## Notifieringar Tasks",
        "",
        "2025.12.01",
        "",
        "## Autogiro",
        "",
        "## Invoice Manager",
    ])
    out, removed = strip_table_of_contents(md)
    assert removed == 7
    assert "Amili 4" not in out and "2025.12.01 8" not in out
    assert "## Integration Amili" in out and "\n2025.12.01\n" in out


def test_prose_with_numbers_is_not_a_contents_page():
    md = "Version 2 kom 2019 och version 3 kom 2021.\n\nText 4 more 5 words 6.\n\n## Version\n"
    assert strip_table_of_contents(md) == (md, 0)


# --- bookmarks ---------------------------------------------------------------


def test_bookmark_links_point_at_heading_anchors():
    html = (
        '<p><a href="#_a1">Inledning\t3</a></p>'
        '<h1><a id="_a1"></a>Inledning</h1><p>x</p>'
        '<h2><a id="_b2"></a>Moms &amp; skatt</h2>'
        '<h2><a id="_c3"></a>Inledning</h2>'
    )
    anchors = heading_bookmarks(html)
    assert anchors == {"_a1": "inledning", "_b2": "moms--skatt", "_c3": "inledning-1"}
    md = "[Inledning 3](#_a1) [Moms](#_b2) [Igen](#_c3) [Bild](#_body9) [Top](#top)"
    assert relink_bookmarks(md, anchors) == (
        "[Inledning 3](#inledning) [Moms](#moms--skatt) [Igen](#inledning-1) "
        "Bild [Top](#top)"
    )


# --- DOCX Title style (end to end) -------------------------------------------


def _title_docx(path: Path) -> None:
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("Budget Control Edge", style="Title")
    doc.add_heading("Systeminställningar", level=1)
    doc.add_paragraph("Body.")
    doc.add_heading("Allmänna", level=3)
    doc.add_heading("Rapporter", level=1)
    doc.save(path)


@pytest.mark.parametrize("normalize, expected", [
    (True, ["# Budget Control Edge", "## Systeminställningar", "### Allmänna", "## Rapporter"]),
    (False, ["# Systeminställningar", "### Allmänna", "# Rapporter"]),
])
def test_docx_title_style_becomes_the_h1(tmp_path, normalize, expected):
    src = tmp_path / "budget.docx"
    _title_docx(src)
    dest = tmp_path / "out" / "budget.md"
    ConversionWorker([ConversionItem(src, dest)], overwrite=True,
                     normalize_headings=normalize).run()
    text = dest.read_text(encoding="utf-8")
    assert [l for l in text.split("\n") if l.startswith("#")] == expected


# --- PDF headings ------------------------------------------------------------


def _lines(*specs: tuple[str, float]) -> list[_Line]:
    out, top = [], 0.0
    for text, size in specs:
        out.append(_Line(text, top, top + size, size))
        top += size * 1.2
    return out


def test_pdf_bullet_and_its_wrapped_line_are_not_headings():
    text = _render_text(_lines(
        ("● Beställning av Kivratjänsten görs via Visma. Ingen beställning", 14),
        ("direkt mellan kund och Inexchange", 14),
    ), body=10)
    assert "#" not in text
    assert text == (
        "● Beställning av Kivratjänsten görs via Visma. Ingen beställning "
        "direkt mellan kund och Inexchange"
    )


def test_pdf_large_font_paragraph_is_not_a_heading():
    text = _render_text(_lines(
        ("Notera. Inställning av olika confidence levels kommer att", 14),
        ("vara synliga i enhetsparameter UseAutosuggest.", 14),
    ), body=10)
    assert not text.startswith("#")


def test_pdf_real_heading_still_detected():
    text = _render_text(_lines(("Integration Amili", 14), ("Body text here.", 10)), body=10)
    assert text.startswith("## Integration Amili")
