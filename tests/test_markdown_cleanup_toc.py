"""Tests for ``strip_table_of_contents`` in ``app.markdown_cleanup``.

The pass runs only when a sidecar index is generated: it removes the
document's own contents page (a heading plus dotted-leader / anchor-link
entries, or a bare dotted-leader run) while leaving all real content — and
in particular body sections that merely *resemble* TOC lines — intact.
"""

from __future__ import annotations

from app.markdown_cleanup import strip_table_of_contents


def test_heading_anchored_dotleader_toc_is_removed():
    md = "\n".join(
        [
            "# Doc Title",
            "",
            "## Table of Contents",
            "",
            "Introduction ................... 3",
            "Scope .......................... 5",
            "Details ........................ 8",
            "",
            "## Introduction",
            "",
            "Real body text starts here.",
        ]
    )
    out, removed = strip_table_of_contents(md)
    assert removed > 0
    assert "Table of Contents" not in out
    assert "..." not in out
    # Body survives.
    assert "## Introduction" in out
    assert "Real body text starts here." in out


def test_singular_heading_and_interspersed_page_numbers():
    """'Table of Content' (no plural) plus TOC-page footer numbers between
    entries — both must be absorbed, stopping at the next real heading."""
    md = "\n".join(
        [
            "## Table of Content",
            "",
            "Notifications ......... 9",
            "Accounts .............. 12",
            "2",  # a contents-page footer number, mid-block
            "Vouchers .............. 20",
            "",
            "## Notifications",
            "Body.",
        ]
    )
    out, removed = strip_table_of_contents(md)
    assert "Table of Content" not in out
    assert "Notifications ........." not in out
    assert "\n2\n" not in out  # footer number gone too
    assert "## Notifications" in out and "Body." in out


def test_headingless_dotleader_run_is_removed():
    md = "\n".join(
        [
            "Intro paragraph.",
            "",
            "Alpha .......... 1",
            "Beta ........... 2",
            "Gamma .......... 3",
            "",
            "Real content.",
        ]
    )
    out, removed = strip_table_of_contents(md)
    assert removed == 3
    assert "Alpha" not in out and "Gamma" not in out
    assert "Intro paragraph." in out and "Real content." in out


def test_markdown_anchor_link_toc_is_removed():
    md = "\n".join(
        [
            "## Contents",
            "",
            "- [Introduction](#introduction)",
            "- [Usage](#usage)",
            "",
            "## Introduction",
            "Body.",
        ]
    )
    out, removed = strip_table_of_contents(md)
    assert "## Contents" not in out
    assert "(#introduction)" not in out
    assert "## Introduction" in out


def test_too_few_dotleaders_are_left_alone():
    """A lone contents-like line in prose is not a TOC."""
    md = "See appendix .......... 42\n\nOrdinary paragraph."
    out, removed = strip_table_of_contents(md)
    assert removed == 0
    assert out == md


def test_body_endpoint_headings_are_preserved():
    """Body definition headings resemble TOC entries but carry no dotted
    leader, so they must never be stripped."""
    md = "\n".join(
        [
            "## Table of Contents",
            "",
            "Post method : /api/create ............ 12",
            "Get method : /api/read ............... 15",
            "Delete method : /api/remove .......... 18",
            "",
            "## Post method : /api/create",
            "",
            "Creates a thing.",
        ]
    )
    out, removed = strip_table_of_contents(md)
    # TOC references gone...
    assert "............" not in out
    # ...but the real definition heading and its body remain.
    assert "## Post method : /api/create" in out
    assert "Creates a thing." in out


def test_code_fence_dotleaders_are_not_touched():
    md = "\n".join(
        [
            "```",
            "output ............ 1",
            "output ............ 2",
            "output ............ 3",
            "```",
        ]
    )
    out, removed = strip_table_of_contents(md)
    assert removed == 0
    assert out == md


def test_no_toc_is_a_no_op():
    md = "# Title\n\nJust prose, no contents page.\n"
    out, removed = strip_table_of_contents(md)
    assert removed == 0
    assert out == md
