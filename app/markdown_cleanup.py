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
