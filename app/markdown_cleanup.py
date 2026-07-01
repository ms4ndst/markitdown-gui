"""Post-process patterns that lint as 'empty heading' in MarkItDown output.

mammoth (MarkItDown's ``.docx`` converter) produces two patterns that fail
markdownlint's ``MD042 / no-empty-headings`` rule:

1. A bare ``#``, ``##`` etc. on a line by itself — typically from a Word
   paragraph styled as *Heading X* that the author left empty (an
   intentional spacer, or a leftover after deleting text).
2. ``## ![alt](url)`` — a heading whose entire content is an inline image.
   The heading has no navigable text, breaks tables of contents, and renders
   identically to the bare image below the heading above it.

Both are stripped before the output is written: (1) by deleting the line,
(2) by demoting the line to the image alone. The original image survives
in case 2 — only the heading prefix goes away.

This pass is *always on*. Empty headings are bad output regardless of which
image-extraction mode the user picked and there is no legitimate reason to
keep them.

In addition to the empty-heading pass, this module exposes ``apply_lint_fixes``
— a batch of safe auto-fixes for the markdownlint rules whose violations have
a single mechanical correction (MD009/MD010/MD012/MD018/MD022/MD025/MD026/
MD029/MD031/MD032/MD034/MD047). MD025 is fixed only when YAML frontmatter
declares a ``title:`` (the demotion is then unambiguous — the doc said its
own title in metadata, the body shouldn't repeat it as H1). Rules that
require human judgment (MD011, MD024, MD033, MD041, MD042, MD045) are left
for the downstream linter.
"""

from __future__ import annotations

import re

# A markdown heading whose only characters after the hashes are whitespace.
# ``\s`` covers tabs, NBSP, and other unicode whitespace mammoth occasionally
# leaves behind.
_EMPTY_HEADING = re.compile(r"^#{1,6}\s*$")

# A heading whose entire content is exactly one inline image. The image is
# kept (it's real content); the heading prefix is removed.
_IMAGE_ONLY_HEADING = re.compile(
    r"^(?P<hashes>#{1,6})\s+(?P<img>!\[[^\]]*\]\([^)]*\))\s*$"
)


# Standalone page-number patterns. Each must match the ENTIRE line content
# (apart from leading/trailing whitespace) so we never strip a number that
# appears inside a paragraph, table cell, or list item. Numbers are bounded
# to 1-4 digits to avoid eating years buried in body text that happen to
# stand alone (a 2026 on its own line is far more likely a stray heading
# than page 2026).
_PAGE_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*\d{1,4}\s*$"),                                       # 5
    re.compile(r"^\s*[-–—]\s*\d{1,4}\s*[-–—]\s*$"),                       # - 5 -
    re.compile(r"^\s*\d{1,4}\s*/\s*\d{1,4}\s*$"),                         # 5/20
    re.compile(r"^\s*page\s+\d{1,4}(\s+of\s+\d{1,4})?\s*$", re.IGNORECASE),  # Page 5 / Page 5 of 20
    re.compile(r"^\s*\d{1,4}\s+of\s+\d{1,4}\s*$", re.IGNORECASE),         # 5 of 20
)


def _looks_like_page_number(line: str) -> bool:
    return any(p.match(line) for p in _PAGE_NUMBER_PATTERNS)


def strip_page_numbers(markdown: str) -> tuple[str, int]:
    """Remove standalone page-number lines from PDF-converted markdown.

    A line is stripped only when (a) its full content matches one of the
    page-number patterns, (b) it sits outside any fenced code block, and
    (c) it is isolated — preceded by a blank line or start-of-file and
    followed by a blank line or end-of-file. The isolation rule keeps the
    pass from touching numeric content that lives inside a paragraph or
    table row.

    Returns ``(new_markdown, removed_count)``.
    """
    lines = markdown.split("\n")
    fence = _compute_fence_lines(lines)
    out: list[str] = []
    removed = 0
    for i, line in enumerate(lines):
        if i in fence or not _looks_like_page_number(line):
            out.append(line)
            continue
        prev_blank = i == 0 or _is_blank(lines[i - 1])
        next_blank = i + 1 == len(lines) or _is_blank(lines[i + 1])
        if prev_blank and next_blank:
            removed += 1
            continue
        out.append(line)
    return "\n".join(out), removed


def strip_headers_footers(
    markdown: str, min_repeats: int = 3, min_length: int = 8
) -> tuple[str, int]:
    """Remove running headers/footers: lines that repeat across many pages.

    PDF text extraction re-emits every page's running header and footer inline
    (a signature banner, a "Page X of Y" strip, a document title bar, ...), so
    the same line ends up scattered identically through the markdown. DOCX
    files never carry the *real* Word header/footer objects into the markdown
    — mammoth only reads the document body — but a banner typed directly into
    the body of every page (common in DOCX exported from PDF) produces the
    identical repeated-line pattern, so this pass is applied to DOCX output
    too. This pass counts each non-blank line (compared on its stripped text)
    and removes every occurrence of a line that:

    * repeats at least ``min_repeats`` times — the core header/footer signal;
    * is at least ``min_length`` characters long, so short repeated words in
      prose ("Ja", "Visma", a lone list marker) are never touched;
    * is not a heading or list item — structural markdown that may legitimately
      recur and carries navigable meaning.

    Frequency is the only page-structure proxy available once the text is a flat
    markdown stream, so a header/footer on a document with fewer than
    ``min_repeats`` pages will not reach the threshold and is deliberately kept
    (better to leave boilerplate than delete real content). Lines inside fenced
    code blocks are never counted or removed. Returns
    ``(new_markdown, removed_count)``.
    """
    lines = markdown.split("\n")
    fence = _compute_fence_lines(lines)

    def _eligible(idx: int, line: str) -> bool:
        if idx in fence:
            return False
        stripped = line.strip()
        if len(stripped) < min_length:
            return False
        if stripped.startswith("#") or _LIST_ITEM_RE.match(line):
            return False
        return True

    counts: dict[str, int] = {}
    for i, line in enumerate(lines):
        if _eligible(i, line):
            counts[line.strip()] = counts.get(line.strip(), 0) + 1

    boiler = {text for text, n in counts.items() if n >= min_repeats}
    if not boiler:
        return markdown, 0

    out: list[str] = []
    removed = 0
    for i, line in enumerate(lines):
        if _eligible(i, line) and line.strip() in boiler:
            removed += 1
            continue
        out.append(line)
    return "\n".join(out), removed


def strip_empty_headings(markdown: str) -> tuple[str, int]:
    """Remove empty heading lines and demote image-only headings.

    Returns ``(new_markdown, altered_count)`` — ``altered_count`` is the
    number of heading lines that were either deleted or demoted, useful for
    a log message.
    """
    out_lines: list[str] = []
    altered = 0
    for line in markdown.splitlines():
        if _EMPTY_HEADING.match(line):
            altered += 1
            continue
        match = _IMAGE_ONLY_HEADING.match(line)
        if match is not None:
            out_lines.append(match.group("img"))
            altered += 1
            continue
        out_lines.append(line)

    new_md = "\n".join(out_lines)
    # splitlines() drops the trailing newline; preserve it so the file's
    # final-newline status is unchanged.
    if markdown.endswith("\n"):
        new_md += "\n"
    return new_md, altered


# ---------------------------------------------------------------------------
# Lint auto-fix pass
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^[ \t]{0,3}(```|~~~)")
_FRONTMATTER_DELIM_RE = re.compile(r"^---\s*$")
_HEADING_LINE_RE = re.compile(r"^(?P<indent>\s*)(?P<hashes>#{1,6})(?P<sep>[ \t]*)(?P<text>.*?)\s*$")
_HASH_NO_SPACE_RE = re.compile(r"^(?P<indent>\s*)(?P<hashes>#{1,6})(?P<rest>[^# \t].*)$")
_TRAILING_PUNCT_RE = re.compile(r"[.,;:!]+$")
_ORDERED_ITEM_RE = re.compile(r"^(?P<indent>\s*)(?P<num>\d+)(?P<delim>[.)])(?P<after>\s+)(?P<text>.*)$")
_LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)(?:[-*+]|\d+[.)])\s+")
# Bare http(s) URL.
#
# Lead accepts: start-of-line, whitespace/NBSP, OR an opening paren that
# is NOT preceded by `]`. The `]` guard preserves real inline links
# `[text](url)` — we must not wrap a URL inside an established link's
# parens — while still wrapping a paren-introduced URL like
# `(https://...)` on its own (a common PDF-extraction artefact).
#
# Stops at the first whitespace, `<`, `>`, `)`, `]`, or backtick — so
# URLs already inside `<...>` / `[...]` / `` `...` `` are never matched.
_BARE_URL_RE = re.compile(
    r"(?P<lead>(?:^|[\s ]|(?<!\])\())(?P<url>https?://[^\s<>)\]`]+?)(?P<trail>[.,;:!?]?(?=$|[\s )]))",
    re.MULTILINE,
)
# Heading punctuation we strip per markdownlint MD026 default set, minus '?'
# (question-headings are idiomatic and removing the '?' would change meaning).
_HEADING_PUNCT_TO_STRIP = set(".,;:!")


def _compute_fence_lines(lines: list[str]) -> set[int]:
    """Return the set of line indices that lie inside (or are) a fenced code block.

    Tracks `` ``` `` and ``~~~`` toggles; an unterminated fence at EOF marks all
    remaining lines as inside-code, which is the conservative choice (we'd
    rather not edit text we can't verify isn't code).
    """
    inside: set[int] = set()
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            inside.add(i)
            in_fence = not in_fence
            continue
        if in_fence:
            inside.add(i)
    return inside


def _compute_frontmatter_end(lines: list[str]) -> int:
    """Index AFTER the closing ``---`` of YAML front matter, or 0 if none.

    Hugo / Jekyll / Hexo content files routinely start with ``---`` ... ``---``
    blocks. We MUST NOT edit inside them - wrapping a URL value in ``<...>`` or
    stripping a trailing colon would break the YAML.
    """
    if not lines or not _FRONTMATTER_DELIM_RE.match(lines[0]):
        return 0
    for i in range(1, len(lines)):
        if _FRONTMATTER_DELIM_RE.match(lines[i]):
            return i + 1
    return 0


def _compute_skip_lines(lines: list[str]) -> set[int]:
    """Lines that mechanical fixers must leave alone: code fences + YAML front matter."""
    skip = _compute_fence_lines(lines)
    for i in range(_compute_frontmatter_end(lines)):
        skip.add(i)
    return skip


def _is_heading_line(line: str) -> bool:
    return bool(_HEADING_LINE_RE.match(line)) and line.lstrip().startswith("#")


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def fix_form_feeds(text: str) -> tuple[str, int]:
    """Strip form-feed (``\\x0c``) characters that pdfminer emits at page
    boundaries.

    The page-break control character survives into the markdown, usually glued
    to the front of the first line of the next page (``\\x0c3.5 Tvister``),
    where it corrupts that line and any heading detection on it. It carries no
    content, so every occurrence is removed. Returns ``(new_markdown, count)``.
    """
    count = text.count("\x0c")
    if count:
        text = text.replace("\x0c", "")
    return text, count


# A numbered section title. Two shapes:
#   * "3.6 Sekretess"  — a multi-level number with no trailing dot (depth >= 2)
#   * "1. Tjänsteutbud" — a single number with a trailing dot (depth 1)
# pdfminer emits both as plain text (the depth-1 ones as ordered-list markers),
# so they render as body paragraphs / list items and run into adjacent text —
# but in the source PDF they are section headings.
_NUMBERED_HEADING_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+)+|\d+\.)\s+(?P<title>\S.*?)\s*$"
)
# A line that is a single-number ordered-list marker (``N.`` / ``N)``). Used to
# detect list clusters so a real list item is not mistaken for a heading.
_NUM_ITEM_LINE_RE = re.compile(r"^\s*\d+[.)]\s")
_BULLET_ITEM_RE = re.compile(r"^\s*[-*+]\s")


def _adjacent_numbered_item(lines: list[str], i: int) -> bool:
    """True if the nearest non-blank neighbour above or below line ``i`` is a
    single-number list marker — i.e. line ``i`` sits inside a list cluster and
    is probably a real ordered-list item, not a standalone section heading."""
    j = i - 1
    while j >= 0 and _is_blank(lines[j]):
        j -= 1
    if j >= 0 and _NUM_ITEM_LINE_RE.match(lines[j]):
        return True
    j = i + 1
    while j < len(lines) and _is_blank(lines[j]):
        j += 1
    return j < len(lines) and bool(_NUM_ITEM_LINE_RE.match(lines[j]))


def fix_numbered_section_headings(text: str) -> tuple[str, int]:
    """Promote numbered section titles (``1. Foo`` / ``3.6 Bar``) to headings.

    A line is promoted only when it is a section number followed by a *short*
    title (<= 50 chars and <= 7 words) that does not end in sentence
    punctuation. Those guards keep long numbered clauses
    ("3.5.1 Uppkommer tvist ... domstol.") — body text, not headings —
    untouched. Bullet items and existing headings are skipped.

    Depth-1 numbers (``1.``) are ambiguous with genuine ordered-list items, so
    one is promoted only when it stands alone (its nearest numbered neighbour is
    not adjacent) — a real list like ``1. / 2. / 3.`` is left as a list. Heading
    level tracks numbering depth (``N.`` -> ``##``, ``N.N`` -> ``###``,
    ``N.N.N`` -> ``####``), capped at H6.

    Must run *before* REJOIN so section titles are no longer list items when the
    continuation-folding pass runs — otherwise the line after a title gets
    merged into it. The downstream MD022 pass adds the surrounding blank lines.
    Returns ``(new_markdown, promoted_count)``.
    """
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    count = 0
    for i, line in enumerate(lines):
        if i in fence or line.lstrip().startswith("#") or _BULLET_ITEM_RE.match(line):
            continue
        m = _NUMBERED_HEADING_RE.match(line)
        if not m:
            continue
        title = m.group("title")
        if len(title) > 50 or len(title.split()) > 7 or title[-1] in ".:,;!":
            continue
        num = m.group("num")
        depth = num.rstrip(".").count(".") + 1  # "1." -> 1, "3.6" -> 2
        if depth == 1 and _adjacent_numbered_item(lines, i):
            continue
        level = min(depth + 1, 6)  # 1 -> ##, 2 -> ###, 3 -> ####
        lines[i] = f"{'#' * level} {num} {title}"
        count += 1
    return "\n".join(lines), count


def fix_hard_tabs(text: str) -> tuple[str, int]:
    """MD010: convert hard tabs to 4 spaces outside code blocks."""
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    count = 0
    for i, line in enumerate(lines):
        if i in fence:
            continue
        if "\t" in line:
            lines[i] = line.replace("\t", "    ")
            count += 1
    return "\n".join(lines), count


def fix_trailing_whitespace(text: str) -> tuple[str, int]:
    """MD009: strip trailing whitespace, preserving exactly 2 trailing spaces
    on non-empty lines (CommonMark soft line break)."""
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    count = 0
    for i, line in enumerate(lines):
        if i in fence:
            continue
        # Compute trailing-whitespace length on the raw line.
        stripped = line.rstrip()
        trail = len(line) - len(stripped)
        if trail == 0:
            continue
        # Soft line break: exactly two trailing spaces (not tabs), non-empty content.
        is_soft_break = (
            trail == 2
            and line.endswith("  ")
            and not line.endswith("\t ")
            and stripped != ""
        )
        new_line = stripped + ("  " if is_soft_break else "")
        if new_line != line:
            lines[i] = new_line
            count += 1
    return "\n".join(lines), count


def fix_missing_hash_space(text: str) -> tuple[str, int]:
    """MD018: ``#Heading`` -> ``# Heading``."""
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    count = 0
    for i, line in enumerate(lines):
        if i in fence:
            continue
        m = _HASH_NO_SPACE_RE.match(line)
        if m:
            lines[i] = f"{m.group('indent')}{m.group('hashes')} {m.group('rest')}"
            count += 1
    return "\n".join(lines), count


def fix_heading_trailing_punctuation(text: str) -> tuple[str, int]:
    """MD026: strip trailing ``.,;:!`` from heading text. ``?`` is preserved."""
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    count = 0
    for i, line in enumerate(lines):
        if i in fence:
            continue
        m = _HEADING_LINE_RE.match(line)
        if not m or not m.group("hashes") or not line.lstrip().startswith("#"):
            continue
        text_part = m.group("text").rstrip()
        if not text_part:
            continue
        stripped = text_part
        while stripped and stripped[-1] in _HEADING_PUNCT_TO_STRIP:
            stripped = stripped[:-1].rstrip()
        if stripped != text_part:
            lines[i] = f"{m.group('indent')}{m.group('hashes')} {stripped}"
            count += 1
    return "\n".join(lines), count


def fix_bare_urls(text: str) -> tuple[str, int]:
    """MD034: wrap bare ``http(s)://`` URLs in ``<...>``. Code-block content
    and URLs already inside parens/brackets/angle-brackets are left alone."""
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    count = 0
    for i, line in enumerate(lines):
        if i in fence:
            continue
        # Skip inline-code spans by splitting on backticks and only touching
        # the non-code segments (even indices).
        parts = line.split("`")
        changed = False
        for j in range(0, len(parts), 2):
            new_part, n = _BARE_URL_RE.subn(
                lambda m: f"{m.group('lead')}<{m.group('url')}>{m.group('trail')}",
                parts[j],
            )
            if n:
                parts[j] = new_part
                count += n
                changed = True
        if changed:
            lines[i] = "`".join(parts)
    return "\n".join(lines), count


def _detect_ol_style(lines: list[str], fence: set[int]) -> str:
    """Mirror markdownlint's MD029 style auto-detect: the first ordered list
    that has at least two items at the same indent + delimiter decides the
    style. ``'one'`` when both items are numbered 1, ``'ordered'`` otherwise.

    Falls back to ``'ordered'`` when no list has two items (single-item lists
    don't constrain the style either way, so the choice is moot).
    """
    first_indent: str | None = None
    first_delim: str | None = None
    first_num: int | None = None
    for i, line in enumerate(lines):
        if i in fence:
            continue
        m = _ORDERED_ITEM_RE.match(line)
        if not m:
            continue
        if first_num is None:
            first_indent = m.group("indent")
            first_delim = m.group("delim")
            first_num = int(m.group("num"))
            continue
        if m.group("indent") == first_indent and m.group("delim") == first_delim:
            second_num = int(m.group("num"))
            if first_num == 1 and second_num == 1:
                return "one"
            return "ordered"
        # Different list — reset to use this list's first item for comparison.
        first_indent = m.group("indent")
        first_delim = m.group("delim")
        first_num = int(m.group("num"))
    return "ordered"


def fix_ordered_list_prefix(text: str) -> tuple[str, int]:
    """MD029: renumber ordered list items to match the document's detected
    style.

    Markdownlint locks one style for the whole document based on the first
    list it sees (either ``1, 2, 3, ...`` or ``1, 1, 1, ...``). We mirror
    that lock so our renumbering doesn't fight the linter — if the doc starts
    with ``1, 1`` we force every list to all-ones; if it starts with ``1, 2``
    we renumber sequentially.

    A list ends when we hit a non-list, non-blank, non-continuation line.
    Nested sub-lists are not specially handled — they're renumbered as part
    of whatever flat sequence they appear in, which matches markdownlint's
    per-level view.

    Single-item blocks are left untouched. A lone ``N.`` separated from other
    numbers by prose is almost always a section heading ("1. Overview",
    "2. Scope", ... spread across pages) whose number carries meaning — the
    old per-block reset rewrote each such heading to ``1.``, collapsing
    "1./2./3." to "1./1./1.". Only a block with two or more items is a real
    ordered list we can safely renumber.
    """
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    style = _detect_ol_style(lines, fence)
    count = 0
    i = 0
    while i < len(lines):
        if i in fence:
            i += 1
            continue
        m = _ORDERED_ITEM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group("indent")
        delim = m.group("delim")
        # Collect this block's item line indices, advancing i past the block
        # (items + their continuation/blank lines at this indent).
        item_indices: list[int] = []
        while i < len(lines):
            if i in fence:
                break
            mi = _ORDERED_ITEM_RE.match(lines[i])
            if mi and mi.group("indent") == indent and mi.group("delim") == delim:
                item_indices.append(i)
                i += 1
                continue
            # Continuation: deeper indent or blank line inside the list.
            if _is_blank(lines[i]) or lines[i].startswith(indent + " "):
                i += 1
                continue
            break
        # Only a multi-item block is a genuine ordered list worth renumbering.
        if len(item_indices) < 2:
            continue
        expected = 1
        for idx in item_indices:
            mi = _ORDERED_ITEM_RE.match(lines[idx])
            actual = int(mi.group("num"))
            if actual != expected:
                after = mi.group("after")
                lines[idx] = f"{indent}{expected}{delim}{after}{mi.group('text')}"
                count += 1
            # one-style: every item stays at 1. ordered-style: bump.
            if style == "ordered":
                expected += 1
    return "\n".join(lines), count


def _block_needs_blank_before(lines: list[str], i: int) -> bool:
    return i > 0 and not _is_blank(lines[i - 1])


def _block_needs_blank_after(lines: list[str], i: int) -> bool:
    return i + 1 < len(lines) and not _is_blank(lines[i + 1])


def fix_blanks_around_headings(text: str) -> tuple[str, int]:
    """MD022: ensure a blank line before and after every heading."""
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    out: list[str] = []
    count = 0
    for i, line in enumerate(lines):
        if i not in fence and _is_heading_line(line):
            if out and out[-1].strip() != "":
                out.append("")
                count += 1
            out.append(line)
            # Look ahead: if next non-current line exists and is non-blank, add one.
            if i + 1 < len(lines) and not _is_blank(lines[i + 1]):
                out.append("")
                count += 1
        else:
            out.append(line)
    return "\n".join(out), count


def fix_blanks_around_fenced_code(text: str) -> tuple[str, int]:
    """MD031: ensure blank lines before/after fenced code blocks (top-level)."""
    lines = text.split("\n")
    out: list[str] = []
    count = 0
    in_fence = False
    for i, line in enumerate(lines):
        is_fence_marker = bool(_FENCE_RE.match(line))
        if is_fence_marker and not in_fence:
            # Opening fence — ensure preceding blank.
            if out and out[-1].strip() != "":
                out.append("")
                count += 1
            out.append(line)
            in_fence = True
            continue
        if is_fence_marker and in_fence:
            # Closing fence — ensure following blank.
            out.append(line)
            in_fence = False
            if i + 1 < len(lines) and not _is_blank(lines[i + 1]):
                out.append("")
                count += 1
            continue
        out.append(line)
    return "\n".join(out), count


def fix_blanks_around_lists(text: str) -> tuple[str, int]:
    """MD032: ensure blank lines before and after lists (top-level only)."""
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    out: list[str] = []
    count = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if i in fence:
            out.append(line)
            i += 1
            continue
        # Top-level list item start: list marker at column 0 indent.
        m = _LIST_ITEM_RE.match(line)
        if m and m.group("indent") == "":
            # Blank before
            if out and out[-1].strip() != "":
                out.append("")
                count += 1
            # Walk through the list (item lines + continuations + blanks within)
            start_idx = i
            while i < len(lines):
                if i in fence:
                    break
                cur = lines[i]
                if _LIST_ITEM_RE.match(cur):
                    out.append(cur)
                    i += 1
                    continue
                # Continuation: indented further than column 0
                if cur.startswith(" ") or cur.startswith("\t"):
                    out.append(cur)
                    i += 1
                    continue
                # Blank line within list — peek ahead: if followed by another list
                # item at this level, it's interior to the list; else it ends it.
                if _is_blank(cur):
                    if i + 1 < len(lines) and _LIST_ITEM_RE.match(lines[i + 1]) and (
                        _LIST_ITEM_RE.match(lines[i + 1]).group("indent") == ""
                    ):
                        out.append(cur)
                        i += 1
                        continue
                    break
                break
            # Blank after
            if i < len(lines) and not _is_blank(lines[i]):
                out.append("")
                count += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out), count


def fix_consecutive_blanks(text: str) -> tuple[str, int]:
    """MD012: collapse runs of 2+ blank lines to a single blank (outside code)."""
    lines = text.split("\n")
    fence = _compute_skip_lines(lines)
    out: list[str] = []
    count = 0
    prev_blank = False
    for i, line in enumerate(lines):
        if i in fence:
            out.append(line)
            prev_blank = False
            continue
        blank = _is_blank(line)
        if blank and prev_blank:
            count += 1
            continue
        out.append(line)
        prev_blank = blank
    return "\n".join(out), count


# A line whose entire content is `N)` for N = 1..999 (with optional leading
# whitespace). In PDF-extracted markdown these are almost always footnote-
# style callouts referencing markers `1)`, `2)`, ... inside a preceding
# table column, NOT real ordered list items. Markdownlint nevertheless
# treats them as a list, which then fights its MD029 style lock.
_BARE_CALLOUT_RE = re.compile(r"^(?P<indent>\s*)(?P<num>\d{1,3})\)\s*$")


def fix_bare_numeric_callouts(text: str) -> tuple[str, int]:
    """Escape the `)` on lines that are *only* ``N)`` so they stop registering
    as ordered list items.

    ``1)`` becomes ``1\\)`` — visually identical in every CommonMark renderer
    (the backslash escapes the close paren) but no longer parsed as a list
    marker, so MD029 / MD032 stop firing on it.

    Lines inside fenced code blocks are left alone. Real ordered list items
    (those with body content after the marker) are unaffected — only the
    bare ``N)``-on-its-own pattern is matched.
    """
    lines = text.split("\n")
    fence = _compute_fence_lines(lines)
    count = 0
    for i, line in enumerate(lines):
        if i in fence:
            continue
        m = _BARE_CALLOUT_RE.match(line)
        if not m:
            continue
        lines[i] = f"{m.group('indent')}{m.group('num')}\\)"
        count += 1
    return "\n".join(lines), count


# Unicode bullet glyphs that PDF text extraction emits literally at the start
# of a list item instead of a real markdown marker. pdfminer (MarkItDown's PDF
# backend) copies the glyph out of the content stream verbatim, so a bulleted
# paragraph arrives as e.g. "● item text" — plain text to every markdown
# renderer, with no list semantics.
#
# Only glyphs that are unambiguous list bullets are included. En/em dashes and
# the middle dot (U+00B7) are deliberately excluded: they occur mid-sentence in
# prose often enough that a line-start match would produce false positives.
_BULLET_GLYPHS = "•‣⁃∙●○◦▪▫□◾◼◻"
_UNICODE_BULLET_RE = re.compile(
    rf"^(?P<indent>\s*)[{_BULLET_GLYPHS}]\s+(?P<text>\S.*)$"
)


def fix_unicode_bullets(text: str) -> tuple[str, int]:
    """Rewrite literal unicode bullet glyphs at line start to markdown ``- ``.

    PDF extraction (pdfminer) copies bullet glyphs such as ``●`` / ``•`` out of
    the content stream as ordinary text, so a bulleted list arrives as a run of
    paragraphs each beginning with the glyph and no list is rendered. Converting
    the leading glyph to ``-`` restores real markdown list semantics, which the
    downstream MD032 pass then spaces correctly.

    Only a leading glyph followed by whitespace and item text is matched;
    indentation is preserved so nested bullets keep their level. Fenced code is
    left untouched. Returns ``(new_markdown, converted_count)``.
    """
    lines = text.split("\n")
    fence = _compute_fence_lines(lines)
    count = 0
    for i, line in enumerate(lines):
        if i in fence:
            continue
        m = _UNICODE_BULLET_RE.match(line)
        if not m:
            continue
        lines[i] = f"{m.group('indent')}- {m.group('text')}"
        count += 1
    return "\n".join(lines), count


# Once a wrapped item's accumulated text ends with one of these, the next
# physical line is new content, not a continuation. Sentence-final punctuation
# is the reliable signal that a PDF-wrapped item has ended.
_ITEM_END_PUNCT = ".!?:;"

# Block-level constructs that can never be a lazy continuation of a list item:
# headings, blockquotes, table rows, fences, and HTML/angle-bracket lines
# (which includes the ``<https://...>`` links MD034 produces on footer lines).
_BLOCK_START_RE = re.compile(r"^\s*(?:#{1,6}\s|>|\||```|~~~|<)")


def fix_orphaned_list_continuations(text: str) -> tuple[str, int]:
    """Rejoin PDF-wrapped continuation lines back into their list item.

    pdfminer hard-wraps long list items across physical lines, so a single
    bullet arrives as::

        - Tillgång till Developer Portal, ... till de
        priser som gäller vid var tid.

    The second line is a lazy continuation (no blank separates it), but the
    downstream MD032 pass would insert a blank before it and split it into its
    own paragraph. This pass folds such continuation lines back onto the item
    line *before* MD032 runs.

    A following line is treated as a continuation only when the accumulated
    item text does not yet end in sentence-final punctuation (``.!?:;``) and
    the line is plain running text — not blank, not another list item, not a
    heading/table/quote/fence/HTML block. That punctuation guard keeps genuine
    trailing paragraphs and page-footer artefacts (which follow a
    period-terminated line) from being swallowed. Runs after ``BULLET`` so
    ``●`` items are already ``-`` markers, and before the block-layout passes.
    Returns ``(new_markdown, joined_count)``.
    """
    lines = text.split("\n")
    fence = _compute_fence_lines(lines)
    out: list[str] = []
    count = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if i in fence or not _LIST_ITEM_RE.match(line):
            out.append(line)
            i += 1
            continue
        # Fold lazy continuations onto this list item.
        item = line
        i += 1
        while i < n and i not in fence:
            nxt = lines[i]
            if _is_blank(nxt) or _LIST_ITEM_RE.match(nxt) or _BLOCK_START_RE.match(nxt):
                break
            if item.rstrip()[-1:] in _ITEM_END_PUNCT:
                break
            item = item.rstrip() + " " + nxt.strip()
            count += 1
            i += 1
        out.append(item)
    return "\n".join(out), count


_FRONTMATTER_TITLE_RE = re.compile(r"^\s*title\s*:\s*\S", re.IGNORECASE)


def fix_md025_with_frontmatter(text: str) -> tuple[str, int]:
    """MD025: when YAML frontmatter contains a ``title:`` field, demote the
    first body H1 to H2.

    Markdownlint's default config treats the frontmatter ``title:`` value as
    the document's H1 — so any ``# Heading`` in the body becomes a second
    top-level heading and fails MD025. The fix is unambiguous: the doc has
    declared its title in metadata, so the body shouldn't repeat it at the
    same level.

    Only the *first* body H1 is touched (any subsequent H1s are left for the
    linter to flag — they're more likely a real authoring error than a PDF
    artefact).
    """
    lines = text.split("\n")
    fm_end = _compute_frontmatter_end(lines)
    if fm_end == 0:
        return text, 0
    has_title = any(_FRONTMATTER_TITLE_RE.match(lines[i]) for i in range(fm_end))
    if not has_title:
        return text, 0
    fence = _compute_fence_lines(lines)
    for i in range(fm_end, len(lines)):
        if i in fence:
            continue
        line = lines[i]
        # Match a level-1 heading only — ``# X`` but not ``## X``.
        stripped = line.lstrip()
        if not stripped.startswith("# ") and stripped != "#":
            continue
        # Demote to H2.
        leading_ws_len = len(line) - len(stripped)
        lines[i] = line[:leading_ws_len] + "#" + line[leading_ws_len:]
        return "\n".join(lines), 1
    return text, 0


def fix_trailing_newline(text: str) -> tuple[str, int]:
    """MD047: file ends with exactly one newline."""
    if text == "":
        return text, 0
    stripped = text.rstrip("\n")
    desired = stripped + "\n"
    return (desired, 0 if desired == text else 1)


# The fix order is load-bearing:
#   0. FORMFEED first so page-break junk never corrupts a heading match.
#   1. MD010 next so subsequent regexes see only spaces.
#   2. Per-line cleanups (MD009/MD018/MD026/MD034/MD029) before block layout.
#      Bullet-glyph normalization (BULLET) and continuation-rejoin (REJOIN)
#      run here too, so PDF ``●`` items become real ``-`` list items and any
#      hard-wrapped item text is folded back before MD032 spaces the list.
#   3. Block layout (MD022/MD031/MD032) adds blank lines.
#   4. MD012 collapses any over-eager runs into a single blank.
#   5. MD047 last so the trailing newline survives all transformations.
_FIX_PIPELINE: tuple[tuple[str, "callable[[str], tuple[str, int]]"], ...] = (  # type: ignore[name-defined]
    ("FORMFEED", fix_form_feeds),
    ("MD010", fix_hard_tabs),
    ("MD025", fix_md025_with_frontmatter),
    ("MD009", fix_trailing_whitespace),
    ("MD018", fix_missing_hash_space),
    ("MD026", fix_heading_trailing_punctuation),
    ("MD034", fix_bare_urls),
    ("BULLET", fix_unicode_bullets),
    ("HEADING", fix_numbered_section_headings),
    ("REJOIN", fix_orphaned_list_continuations),
    ("CALLOUT", fix_bare_numeric_callouts),
    ("MD029", fix_ordered_list_prefix),
    ("MD022", fix_blanks_around_headings),
    ("MD031", fix_blanks_around_fenced_code),
    ("MD032", fix_blanks_around_lists),
    ("MD012", fix_consecutive_blanks),
    ("MD047", fix_trailing_newline),
)


def apply_lint_fixes(markdown: str) -> tuple[str, dict[str, int]]:
    """Run every safe markdownlint auto-fix in the correct order.

    Returns ``(new_markdown, fixes_by_rule)`` where ``fixes_by_rule`` only
    contains rules that actually changed something — empty dict means the
    output was already clean by these rules.
    """
    counts: dict[str, int] = {}
    for rule, fix in _FIX_PIPELINE:
        markdown, n = fix(markdown)
        if n > 0:
            counts[rule] = n
    return markdown, counts
