"""Generate a sidecar ``<name>.index.md`` for large converted files.

The index helps an LLM (or a human) navigate a long file without having to
read every line. Detection runs in layers and merges the results:

* **Markdown headings** — ``#`` through ``######`` lines that already exist.
* **Numbered sections** — ``1``, ``1.1``, ``1.1.2`` style headings common
  in technical manuals, with the depth derived from dot count.
* **Named sections** — ``Chapter X``, ``Section 4``, ``Appendix A``,
  ``Part II``, ``Annex B`` and similar.
* **ALL CAPS lines** that look like display headings (short, surrounded
  by blank lines or followed by prose).
* **Endpoint mentions** — ``GET /api/...`` or ``Get method : /api/...`` —
  grouped by their first path segment.

Repeated page headers / footers are detected and removed so they don't
flood the index with the same line numbers per page.
"""

from __future__ import annotations

import re
from collections import Counter

MIN_LINES_FOR_INDEX = 500

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

NUMBERED_HEADING_RE = re.compile(
    r"^\s*(\d+(?:\.\d+){0,5})\.?\s+(\S.{0,120})$"
)

NAMED_HEADING_RE = re.compile(
    r"^\s*(Chapter|Section|Part|Appendix|Annex)\s+"
    r"([IVXLCDM]+|\d+)\b"
    r"[\s:.\-–—]*"
    r"(.{0,120})?$",
    re.IGNORECASE,
)

METHOD_LABEL_RE = re.compile(
    r"^\s*(Get|Post|Put|Patch|Delete)\s+method\s*[:\-]?\s*"
    r"(/[A-Za-z0-9_\-{}/.]+)",
    re.IGNORECASE,
)

INLINE_ENDPOINT_RE = re.compile(
    r"^\s*(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_\-{}/.]+)\s*$",
    re.IGNORECASE,
)


def should_index(markdown: str) -> bool:
    return markdown.count("\n") + 1 >= MIN_LINES_FOR_INDEX


def _group_key(path: str) -> str:
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0].lower() in {"api", "v1", "v2"}:
        return parts[1]
    return parts[0] if parts else path


_CODE_CHARS = set("(){}[]<>=;*+|/\\\"'`")


def _looks_like_code(line: str) -> bool:
    """Reject any line that contains characters typical of code, not prose."""
    return any(ch in _CODE_CHARS for ch in line)


def _is_all_caps_heading(line: str) -> bool:
    s = line.strip()
    if not (5 <= len(s) <= 80):
        return False
    if _looks_like_code(s):
        return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4:
        return False
    if not all(c.isupper() for c in letters):
        return False
    if s.endswith((".", ":", ",", ";")):
        return False
    words = s.split()
    return 1 <= len(words) <= 10


def _is_title_case_heading(line: str) -> bool:
    s = line.strip()
    if not (8 <= len(s) <= 80):
        return False
    if _looks_like_code(s):
        return False
    if s.endswith((".", ":", ",", ";")):
        return False
    words = [w for w in s.split() if any(c.isalpha() for c in w)]
    if not (2 <= len(words) <= 10):
        return False
    capped = sum(1 for w in words if w[0].isupper())
    return capped / len(words) >= 0.7


def _find_repeated_lines(lines: list[str], min_repeats: int = 4) -> set[str]:
    """Identify lines that repeat often enough to be page headers/footers.

    A typical PDF puts the same banner ("Acme Software AB", "Page 3 of 75",
    document title) on every page. These get extracted as separate lines and
    would otherwise flood the index. Any non-trivial line that appears
    ``min_repeats`` times or more is treated as boilerplate.
    """
    counter: Counter[str] = Counter()
    for line in lines:
        s = line.strip()
        if 3 <= len(s) <= 120:
            counter[s] += 1
    return {s for s, n in counter.items() if n >= min_repeats}


def _scan_headings(
    lines: list[str],
    boilerplate: set[str],
) -> list[tuple[int, str, int]]:
    """Return ``(level, title, line_no)`` triples in source order.

    Later post-processing dedupes consecutive identical hits and trims hits
    whose source line repeats too often (page headers leak in here when they
    happen to look heading-like).
    """
    results: list[tuple[int, str, int]] = []

    for i, raw_line in enumerate(lines):
        s = raw_line.strip()
        if not s or s in boilerplate:
            continue
        if s.startswith("|"):
            continue

        m = HEADING_RE.match(raw_line)
        if m:
            results.append((len(m.group(1)), m.group(2).strip(), i + 1))
            continue

        prev_blank = i == 0 or not lines[i - 1].strip()
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        next_blank = not next_line.strip()
        next_is_prose = len(next_line.strip()) > 60

        m = NUMBERED_HEADING_RE.match(raw_line)
        if m:
            num = m.group(1)
            title = m.group(2).strip().rstrip(".")
            has_dot_in_num = "." in num
            if (
                _looks_like_real_heading_text(title)
                and not _looks_like_code(title)
                and (has_dot_in_num or prev_blank)
            ):
                level = min(6, num.count(".") + 1)
                results.append((level, f"{num} {title}", i + 1))
                continue

        m = NAMED_HEADING_RE.match(raw_line)
        if m:
            kind = m.group(1).title()
            ident = m.group(2)
            tail = (m.group(3) or "").strip().rstrip(".")
            label = f"{kind} {ident}" + (f" — {tail}" if tail else "")
            results.append((1, label, i + 1))
            continue

        if _is_all_caps_heading(raw_line) and (prev_blank or next_blank or next_is_prose):
            results.append((2, s.title(), i + 1))
            continue

        if (
            prev_blank
            and next_is_prose
            and _is_title_case_heading(raw_line)
        ):
            results.append((3, s, i + 1))

    return results


def _looks_like_real_heading_text(title: str) -> bool:
    """Reject numbered hits whose title is just a number, page ref, or junk."""
    s = title.strip()
    if not s:
        return False
    if s.replace(".", "").replace(",", "").replace(" ", "").isdigit():
        return False
    if len(s) < 2:
        return False
    return True


def _dedupe_headings(
    headings: list[tuple[int, str, int]],
) -> list[tuple[int, str, int]]:
    """Drop consecutive duplicates and titles that recur too often.

    A title that appears more than 10 times across the file is almost
    certainly a page banner that snuck past the boilerplate filter; keep the
    first occurrence only so the index still points to it.
    """
    if not headings:
        return headings

    title_counts = Counter(h[1] for h in headings)
    out: list[tuple[int, str, int]] = []
    seen_busy: set[str] = set()
    prev_title: str | None = None

    for level, title, ln in headings:
        if title == prev_title:
            continue
        if title_counts[title] > 10:
            if title in seen_busy:
                continue
            seen_busy.add(title)
        out.append((level, title, ln))
        prev_title = title
    return out


def build_index(markdown: str, source_name: str = "") -> str:
    lines = markdown.split("\n")
    boilerplate = _find_repeated_lines(lines)

    headings = _dedupe_headings(_scan_headings(lines, boilerplate))

    endpoints: list[tuple[str, str, int]] = []
    for i, line in enumerate(lines, start=1):
        if line.strip() in boilerplate:
            continue
        m = METHOD_LABEL_RE.match(line)
        if m:
            endpoints.append((m.group(1).upper(), m.group(2).rstrip("."), i))
            continue
        m = INLINE_ENDPOINT_RE.match(line)
        if m:
            endpoints.append((m.group(1).upper(), m.group(2).rstrip("."), i))

    out: list[str] = []
    title = f"Index of {source_name}" if source_name else "Index"
    out.append(f"# {title}")
    out.append("")
    parts = []
    if headings:
        parts.append(f"{len(headings)} sections")
    if endpoints:
        parts.append(f"{len(endpoints)} endpoints")
    summary = ", ".join(parts) if parts else "no structured sections detected"
    out.append(
        f"Auto-generated navigation index. {summary}. "
        f"Line numbers refer to the main file."
    )
    out.append("")

    if headings:
        out.append("## Sections")
        out.append("")
        for level, htitle, ln in headings:
            indent = "  " * max(0, level - 1)
            out.append(f"{indent}- {htitle} (line {ln})")
        out.append("")

    if endpoints:
        out.append("## Endpoints")
        out.append("")
        grouped: dict[str, list[tuple[str, str, int]]] = {}
        for method, path, ln in endpoints:
            grouped.setdefault(_group_key(path), []).append((method, path, ln))
        for group in sorted(grouped, key=str.lower):
            out.append(f"### {group}")
            out.append("")
            for method, path, ln in grouped[group]:
                out.append(f"- `{method} {path}` (line {ln})")
            out.append("")

    if not headings and not endpoints:
        out.append("_No headings, sections, or endpoint patterns were detected._")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
