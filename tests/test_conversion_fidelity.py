"""Regression tests for conversion defects found in a Google Drive export:

* mixed bold/italic DOCX runs rendering stray literal asterisks,
* emphasis on punctuation rendering stray literal asterisks,
* Word / Google Docs TOC paragraphs (``[Title](#_bookmark) 4``) surviving
  the TOC strip, and
* PPTX slide images linked to made-up ``<shape>.jpg`` files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from markitdown.converters import HtmlConverter

from app.docx_converter import merge_adjacent_emphasis
from app.markdown_cleanup import strip_table_of_contents
from app.worker import ConversionItem, ConversionWorker


def _md(html: str) -> str:
    return HtmlConverter().convert_string(merge_adjacent_emphasis(html)).markdown.strip()


@pytest.mark.parametrize(
    "html, expected",
    [
        # bold-italic word followed by an italic run (mammoth's shape)
        ("<p><strong><em>Anm</em></strong><em>: Samma kommando.</em></p>",
         "***Anm**: Samma kommando.*"),
        # italic, bold-italic, italic period
        ("<p><em>Fördelas med</em><strong><em> två procent</em></strong><em>. </em></p>",
         "*Fördelas med **två procent**.*"),
        # italic on a lone period after a word
        ("<p>innan den är attesterad<em>.</em></p>", "innan den är attesterad."),
        # bold run starting with punctuation
        ("<p>betalningssätt<strong>, VOP</strong>, vidare</p>",
         "betalningssätt, **VOP**, vidare"),
        # plain emphasis is untouched
        ("<p>Plain <strong>bold</strong> and <em>it</em> text</p>",
         "Plain **bold** and *it* text"),
    ],
)
def test_emphasis_renders_without_stray_asterisks(html, expected):
    assert _md(html) == expected


def test_google_docs_toc_paragraphs_are_stripped():
    md = "\n".join([
        "**Budget Control Edge**",
        "",
        "[**Budget**](#_30j0zll) **4**",
        "",
        "[Fördelningsnycklar](#_3znysh7) 6",
        "",
        "[Budgettyper](#_2et92p0) 7",
        "",
        "# Budget",
        "",
        "Body text with a [link](#_3znysh7) inside prose.",
    ])
    out, removed = strip_table_of_contents(md)
    assert removed == 5
    assert "](#_30j0zll)" not in out and "Budgettyper" not in out
    assert "# Budget" in out and "inside prose" in out


def test_two_bookmark_links_are_not_a_toc():
    md = "[One](#_a) 1\n\n[Two](#_b) 2\n\n# Heading\n"
    assert strip_table_of_contents(md) == (md, 0)


def _toc_doc(body_lines: int) -> str:
    toc = [f"[Section {n}](#_s{n}) {n}" for n in range(1, 6)]
    body = ["# Section 1", ""] + [f"Line {n}." for n in range(body_lines)]
    return "\n\n".join(toc) + "\n\n" + "\n".join(body) + "\n"


def _convert(tmp_path: Path, text: str) -> str:
    src = tmp_path / "doc.md"
    src.write_text(text, encoding="utf-8")
    dest = tmp_path / "out" / "doc.md"
    worker = ConversionWorker([ConversionItem(src, dest)], overwrite=True,
                              generate_index=True)
    worker.run()
    return dest.read_text(encoding="utf-8")


def test_toc_kept_when_file_too_short_for_an_index(tmp_path):
    out = _convert(tmp_path, _toc_doc(20))
    # Kept, as a link list without the page numbers.
    assert "- [Section 3](#_s3)\n- [Section 4](#_s4)" in out
    assert "(#_s3) 3" not in out
    assert not (tmp_path / "out" / "doc.index.md").exists()


def test_toc_removed_when_index_is_written(tmp_path):
    out = _convert(tmp_path, _toc_doc(600))
    assert "](#_s3)" not in out
    assert (tmp_path / "out" / "doc.index.md").is_file()


# --- PPTX images -------------------------------------------------------------


def _make_pptx(path: Path) -> None:
    pptx = pytest.importorskip("pptx")
    from PIL import Image

    png = path.with_suffix(".png")
    Image.new("RGB", (8, 8), (200, 30, 30)).save(png)
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Slide one"
    pic = slide.shapes.add_picture(str(png), 0, 0)
    pic.name = "Google Shape;64;p1"
    prs.save(path)


def _convert_pptx(tmp_path: Path, **options) -> tuple[str, Path]:
    src = tmp_path / "deck.pptx"
    _make_pptx(src)
    dest = tmp_path / "out" / "deck.md"
    ConversionWorker([ConversionItem(src, dest)], overwrite=True, **options).run()
    return dest.read_text(encoding="utf-8"), dest


def test_pptx_images_extracted_in_place(tmp_path):
    text, dest = _convert_pptx(tmp_path, extract_pdf_images=True)
    assert "GoogleShape64p1.jpg" not in text
    assert "## Embedded images" not in text
    link = text.split("](", 1)[1].split(")", 1)[0]
    assert link.startswith("images/") and (dest.parent / link).is_file()
    # The image sits on its slide, not in an appendix at the end.
    assert text.index("<!-- Slide number: 1 -->") < text.index("](images/")


def test_pptx_images_embedded_in_place(tmp_path):
    text, _dest = _convert_pptx(tmp_path, embed_pdf_images=True)
    assert "GoogleShape64p1.jpg" not in text
    assert "](data:image/" in text
    assert "## Embedded images" not in text


def test_pptx_placeholder_links_dropped_without_image_mode(tmp_path):
    text, _dest = _convert_pptx(tmp_path)
    assert "GoogleShape64p1.jpg" not in text
    assert "Slide one" in text
