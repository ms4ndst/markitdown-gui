"""DOCX conversion tuned for clean, well-structured Markdown.

Two fixes over MarkItDown's built-in DocxConverter:

**Document title.** mammoth has no mapping for Word's *Title* paragraph
style, so a document's title comes out as a plain paragraph while its
chapters (Heading 1) all become ``#`` — no real title and many H1s. When a
document uses the Title style, it is mapped to H1 and Heading 1–5 shift
down to H2–H6, so the title is the one top-level heading.

**Bookmark links.** Table-of-contents entries and cross-references link to
Word bookmarks (``#_30j0zll``, ``#_Toc123``). mammoth keeps the bookmark as
``<a id>`` inside its heading, but the HTML → Markdown step drops it, so
every such link would lead nowhere. Links to a bookmark in a heading are
pointed at that heading's anchor (the slug GitHub, VS Code and most
renderers generate); links to any other bookmark become plain text.

**Mixed bold / italic.** Word (and Google Docs' DOCX export) stores formatting per *run*, so a
sentence that is italic throughout with one bold-italic word is three runs.
mammoth turns them into sibling elements::

    <strong><em>Anm</em></strong><em>: Samma kommando …</em>

and the HTML → Markdown step renders each one on its own, giving
``***Anm****: Samma kommando …*``. A run of four asterisks can only *close*
emphasis, so the trailing italic never opens and a literal ``*`` shows up in
the rendered text. The fix is to merge the siblings before conversion —
``<em><strong>Anm</strong>: Samma kommando …</em>`` — which renders as
``***Anm**: Samma kommando …*``.
"""

from __future__ import annotations

import html as html_lib
import re
import unicodedata
import zipfile
from collections import Counter
from typing import Any, BinaryIO

from markitdown.converters import DocxConverter, HtmlConverter

# Title -> H1, Heading N -> H(N+1). Matched by style name, as mammoth's own
# defaults are, so it works for Word and Google Docs exports alike.
TITLE_STYLE_MAP = "\n".join(
    ["p[style-name='Title'] => h1:fresh"]
    + [f"p[style-name='Heading {n}'] => h{min(n + 1, 6)}:fresh" for n in range(1, 7)]
)

_TITLE_STYLE_ID_RE = re.compile(
    r'<w:style\b[^>]*w:styleId="([^"]+)"[^>]*>\s*<w:name w:val="Title"\s*/>'
)
_PARAGRAPH_RE = re.compile(r"<w:p\b.*?</w:p>", re.DOTALL)
_TEXT_RE = re.compile(r"<w:t\b[^>]*>([^<]+)</w:t>")


def uses_title_style(file_stream: BinaryIO) -> bool:
    """True if the document has a non-empty paragraph in the Title style.

    Leaves the stream at the position it was given.
    """
    position = file_stream.tell()
    try:
        file_stream.seek(0)
        with zipfile.ZipFile(file_stream) as archive:
            styles = archive.read("word/styles.xml").decode("utf-8", "replace")
            match = _TITLE_STYLE_ID_RE.search(styles)
            if not match:
                return False
            marker = f'<w:pStyle w:val="{match.group(1)}"/>'
            document = archive.read("word/document.xml").decode("utf-8", "replace")
            return any(
                "".join(_TEXT_RE.findall(para)).strip()
                for para in _PARAGRAPH_RE.findall(document)
                if marker in para
            )
    except (KeyError, zipfile.BadZipFile, OSError):
        return False
    finally:
        file_stream.seek(position)

_INLINE_TAG = r"</?(?:em|strong)\b"

# ``<strong><em>X</em></strong>`` with no further em/strong inside X: swap the
# nesting so the italic is outermost and can merge with neighbouring italics.
_STRONG_EM_RE = re.compile(
    r"<strong><em>((?:(?!" + _INLINE_TAG + r").)*?)</em></strong>", re.DOTALL
)
# A closing tag immediately followed by an opening tag of the same kind
# (whitespace between them is kept, as text).
_ADJACENT_EM_RE = re.compile(r"</em>(\s*)<em>")
_ADJACENT_STRONG_RE = re.compile(r"</strong>(\s*)<strong>")


# An innermost em/strong: plain text, possibly with images, no nested tags.
_INNER_EMPHASIS_RE = re.compile(
    r"<(em|strong)>((?:[^<]|<img\b[^>]*>)*)</\1>"
)
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>")


def _is_edge_char(ch: str) -> bool:
    """Punctuation or whitespace — what may not sit just inside an emphasis
    delimiter that touches a word (CommonMark's flanking rules)."""
    return ch.isspace() or unicodedata.category(ch).startswith(("P", "S"))


def _trim_emphasis(match: re.Match) -> str:
    """Move punctuation out of an emphasis run, or drop the run if that is
    all it holds.

    Word lets an author make a lone period italic or start a bold run with
    a comma (``betalningssätt<strong>, VOP</strong>``). Rendered as Markdown,
    an asterisk between a letter and punctuation cannot open or close
    emphasis, so it shows as a literal ``*``. Emphasis on punctuation is
    invisible in practice, so moving it outside loses nothing.
    """
    tag, inner = match.group(1), match.group(2)
    text = html_lib.unescape(_IMG_TAG_RE.sub("", inner))
    if not text.strip() or all(_is_edge_char(ch) for ch in text):
        return inner
    if _IMG_TAG_RE.search(inner) or "&" in inner:
        return match.group(0)
    start, end = 0, len(inner)
    while start < end and _is_edge_char(inner[start]):
        start += 1
    while end > start and _is_edge_char(inner[end - 1]):
        end -= 1
    return f"{inner[:start]}<{tag}>{inner[start:end]}</{tag}>{inner[end:]}"


def merge_adjacent_emphasis(html: str) -> str:
    """Merge sibling ``<em>`` / ``<strong>`` runs so emphasis nests cleanly,
    and keep punctuation outside emphasis so every delimiter can flank."""
    if "<em>" not in html and "<strong>" not in html:
        return html
    html = _STRONG_EM_RE.sub(r"<em><strong>\1</strong></em>", html)
    previous = None
    while previous != html:
        previous = html
        html = _ADJACENT_EM_RE.sub(r"\1", html)
        html = _ADJACENT_STRONG_RE.sub(r"\1", html)
    return _INNER_EMPHASIS_RE.sub(_trim_emphasis, html)


_HTML_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.DOTALL)
_BOOKMARK_ID_RE = re.compile(r'<a id="([^"]+)"\s*>\s*</a>')
_TAG_RE = re.compile(r"<[^>]+>")
# ``[text](#target)``; text may contain one level of brackets (images).
_ANCHOR_LINK_RE = re.compile(r"\[((?:[^\[\]\n]|\[[^\]\n]*\])*)\]\(#([^)\s]+)\)")
_SLUG_DROP_RE = re.compile(r"[^\w\- ]")


def heading_slug(text: str) -> str:
    """The anchor GitHub-style renderers give a heading with this text."""
    return _SLUG_DROP_RE.sub("", text.strip().lower()).replace(" ", "-")


def heading_bookmarks(html: str) -> dict[str, str]:
    """Map each bookmark id inside a heading to that heading's anchor.

    Duplicate heading texts get ``-1``, ``-2`` … as renderers number them.
    Empty headings (removed later by the cleanup) are skipped.
    """
    seen: Counter[str] = Counter()
    anchors: dict[str, str] = {}
    for match in _HTML_HEADING_RE.finditer(html):
        inner = match.group(2)
        text = html_lib.unescape(_TAG_RE.sub("", inner)).strip()
        if not text:
            continue
        slug = heading_slug(text)
        anchor = slug if not seen[slug] else f"{slug}-{seen[slug]}"
        seen[slug] += 1
        for bookmark in _BOOKMARK_ID_RE.findall(inner):
            anchors[bookmark] = anchor
    return anchors


def relink_bookmarks(markdown: str, anchors: dict[str, str]) -> str:
    """Point ``#bookmark`` links at heading anchors; unwrap the rest.

    Only targets that are bookmarks of this document are changed — Word's
    start with ``_`` — so a link to an ordinary ``#anchor`` is left alone.
    """

    def repl(match: re.Match) -> str:
        text, target = match.group(1), match.group(2)
        if target in anchors:
            return f"[{text}](#{anchors[target]})"
        if target.startswith("_"):
            return text
        return match.group(0)

    return _ANCHOR_LINK_RE.sub(repl, markdown)


class _EmphasisMergingHtmlConverter(HtmlConverter):
    def convert_string(self, html_content: str, *args: Any, **kwargs: Any):
        anchors = heading_bookmarks(html_content)
        result = super().convert_string(
            merge_adjacent_emphasis(html_content), *args, **kwargs
        )
        if "](#" in result.markdown:
            result.markdown = relink_bookmarks(result.markdown, anchors)
        return result


class CleanDocxConverter(DocxConverter):
    """MarkItDown's DocxConverter with the title mapping and
    :func:`merge_adjacent_emphasis`. Registered ahead of the built-in one."""

    def __init__(self, map_title: bool = True) -> None:
        super().__init__()
        self._html_converter = _EmphasisMergingHtmlConverter()
        self._map_title = map_title

    def convert(self, file_stream: BinaryIO, stream_info: Any, **kwargs: Any):
        if self._map_title and uses_title_style(file_stream):
            caller = kwargs.get("style_map")
            kwargs["style_map"] = (
                f"{caller}\n{TITLE_STYLE_MAP}" if caller else TITLE_STYLE_MAP
            )
        return super().convert(file_stream, stream_info, **kwargs)
