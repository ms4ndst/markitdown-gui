"""Extract embedded images from a document, either inline as base64 or as
files on disk.

MarkItDown's text converters drop the images embedded in a document — they
only keep the extracted text. This module runs as a *post-processing* step
and appends the images to the Markdown the text converter produced, in one
of two modes the user picks in the GUI:

* **Base64** (:func:`extract_document_images_markdown`) — images are inlined
  as ``data:`` URIs, keeping the ``.md`` self-contained (no extra files).
* **Files** (:func:`extract_document_images_to_files`) — images are written
  to an ``images/`` subfolder next to the ``.md`` and referenced with
  relative links, keeping the Markdown small and the images reusable.

Appending (rather than weaving images inline at their original position) keeps
the behaviour predictable and avoids fighting the layout-detection logic in the
text/table converters. PDF images are grouped by page; other formats emit a
single section.

Two backends are used:

* **PDF** — PyMuPDF (``fitz``) decodes / rasterises the original image bytes.
  Ships with ``markitdown[all]`` via the PDF extras; if missing, PDF
  extraction degrades gracefully to an empty string.
* **OOXML / EPUB** — Python's stdlib :mod:`zipfile`. ``.docx`` / ``.pptx`` /
  ``.xlsx`` / ``.epub`` are all ZIP containers with image bytes stored under
  known paths; nothing extra to install.
"""

from __future__ import annotations

import base64
import hashlib
import re
import zipfile
from pathlib import Path
from typing import Callable, Iterator

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - exercised only on minimal installs
    fitz = None  # type: ignore[assignment]


# Images smaller than this in either dimension are almost always rules,
# spacers or single-pixel artefacts rather than real figures. Skipping them
# keeps the output free of noise.
MIN_DIMENSION = 4

# Subfolder (relative to the .md file) that PNG files are written into.
DEFAULT_IMAGE_SUBFOLDER = "images"

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def pymupdf_available() -> bool:
    """Return True if image extraction is possible in this environment."""
    return fitz is not None


def _missing_pymupdf(log: Callable[[str], None] | None) -> str:
    if log is not None:
        log(
            "  ! PDF image extraction is on but PyMuPDF is not installed — "
            "skipping. Install with `pip install pymupdf`."
        )
    return ""


def _open(pdf_path: str | Path, log: Callable[[str], None] | None):
    try:
        return fitz.open(str(pdf_path))
    except Exception as exc:  # noqa: BLE001 - report and move on
        if log is not None:
            log(f"  ! Could not open PDF for image extraction: {exc}")
        return None


def _iter_unique_images(doc) -> Iterator[tuple[int, int]]:
    """Yield ``(page_index, xref)`` for each image, de-duplicated globally.

    The same embedded image (xref) is frequently referenced from several pages
    (e.g. a header logo). De-duplicating means each image is emitted once, under
    the first page that references it — no bloat, no duplicate files.
    """
    seen: set[int] = set()
    for page_index in range(doc.page_count):
        page = doc[page_index]
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            yield page_index, xref


def _group_markdown(pages: dict[int, list[str]], total: int,
                    log: Callable[[str], None] | None, summary: str) -> str:
    if not pages:
        if log is not None:
            log("  -> no embedded images found to extract")
        return ""
    chunks = [
        f"### Page {page_index + 1}\n\n" + "\n\n".join(lines)
        for page_index, lines in sorted(pages.items())
    ]
    if log is not None:
        log(f"  -> {summary.format(total=total)}")
    return "## Embedded images\n\n" + "\n\n".join(chunks)


def extract_pdf_images_markdown(
    pdf_path: str | Path,
    *,
    min_dimension: int = MIN_DIMENSION,
    log: Callable[[str], None] | None = None,
) -> str:
    """Return a Markdown section embedding every image in ``pdf_path`` as a
    base64 ``data:`` URI, grouped by page.

    Returns an empty string when PyMuPDF is unavailable, the PDF has no
    embedded images, or it cannot be opened. Never raises — image embedding is
    best-effort and must not abort the conversion of a file.
    """
    if fitz is None:
        return _missing_pymupdf(log)
    doc = _open(pdf_path, log)
    if doc is None:
        return ""

    pages: dict[int, list[str]] = {}
    total = 0
    try:
        for page_index, xref in _iter_unique_images(doc):
            try:
                info = doc.extract_image(xref)
            except Exception:  # noqa: BLE001 - skip an unreadable image
                continue
            if not info:
                continue
            data = info.get("image")
            if not data:
                continue
            width = int(info.get("width", 0))
            height = int(info.get("height", 0))
            if width < min_dimension or height < min_dimension:
                continue

            ext = info.get("ext") or "png"
            b64 = base64.b64encode(data).decode("ascii")
            alt = f"Page {page_index + 1} image {xref} ({width}x{height})"
            pages.setdefault(page_index, []).append(
                f"![{alt}](data:image/{ext};base64,{b64})"
            )
            total += 1
    finally:
        doc.close()

    return _group_markdown(pages, total, log, "embedded {total} image(s) as base64")


def _safe_stem(name: str) -> str:
    """Make a Markdown-link- and filesystem-safe basename from ``name``."""
    cleaned = _UNSAFE_NAME_CHARS.sub("_", name).strip("._-")
    return cleaned or "image"


def extract_pdf_images_to_files(
    pdf_path: str | Path,
    output_md_path: str | Path,
    *,
    min_dimension: int = MIN_DIMENSION,
    subfolder: str = DEFAULT_IMAGE_SUBFOLDER,
    log: Callable[[str], None] | None = None,
) -> str:
    """Write every image in ``pdf_path`` to PNG files in ``<md_dir>/<subfolder>/``
    and return a Markdown section linking them with relative paths, grouped by
    page.

    Filenames are prefixed with the ``.md`` stem so several documents converted
    into the same directory can share one ``images/`` folder without colliding.
    All images are rasterised to PNG regardless of their stored format.

    Returns an empty string when PyMuPDF is unavailable, the PDF has no embedded
    images, or it cannot be opened. Never raises — extraction is best-effort and
    must not abort the conversion of a file.
    """
    if fitz is None:
        return _missing_pymupdf(log)
    doc = _open(pdf_path, log)
    if doc is None:
        return ""

    md_path = Path(output_md_path)
    image_dir = md_path.parent / subfolder
    name_prefix = _safe_stem(md_path.stem)

    pages: dict[int, list[str]] = {}
    total = 0
    try:
        for page_index, xref in _iter_unique_images(doc):
            try:
                pix = fitz.Pixmap(doc, xref)
            except Exception:  # noqa: BLE001 - skip an unreadable image
                continue
            try:
                width, height = pix.width, pix.height
                if width < min_dimension or height < min_dimension:
                    continue
                # PNG can't hold CMYK / other multi-channel colourspaces, so
                # convert those (and anything that isn't gray/RGB) to RGB first.
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                filename = f"{name_prefix}_p{page_index + 1}_{xref}.png"
                try:
                    image_dir.mkdir(parents=True, exist_ok=True)
                    pix.save(str(image_dir / filename))
                except Exception as exc:  # noqa: BLE001 - report and skip
                    if log is not None:
                        log(f"  ! Could not write {filename}: {exc}")
                    continue
            finally:
                pix = None  # release the pixmap's buffer promptly

            alt = f"Page {page_index + 1} image {xref} ({width}x{height})"
            # Markdown links always use forward slashes, even on Windows.
            pages.setdefault(page_index, []).append(
                f"![{alt}]({subfolder}/{filename})"
            )
            total += 1
    finally:
        doc.close()

    return _group_markdown(
        pages, total, log,
        f"extracted {{total}} image(s) to {subfolder}/",
    )


# === ZIP-based document formats =====================================
# OOXML (.docx/.pptx/.xlsx) and EPUB all wrap their media in a ZIP. We
# pull the raw image bytes out and emit the same Markdown shape the PDF
# extractors produce, so the worker can treat every format uniformly.

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

# OOXML stores media under a fixed prefix per format. EPUB scatters images
# across the archive (cover, chapter dirs, OEBPS/, etc.), so for it we walk
# every entry and filter by extension.
_OOXML_MEDIA_PREFIX: dict[str, str] = {
    ".docx": "word/media/",
    ".pptx": "ppt/media/",
    ".xlsx": "xl/media/",
}
_ZIP_DOCUMENT_EXTS = set(_OOXML_MEDIA_PREFIX) | {".epub"}


def _mime_for_ext(ext: str) -> str:
    """Map a file extension to its ``image/<mime>`` subtype."""
    return {".jpg": "jpeg", ".tif": "tiff"}.get(ext, ext.lstrip("."))


def _iter_zip_document_images(
    src_path: str | Path,
    log: Callable[[str], None] | None,
) -> Iterator[tuple[str, bytes, str]]:
    """Yield ``(entry_name, bytes, ext)`` for each image inside ``src_path``.

    Routes by file extension: OOXML reads from the format-specific media
    folder, EPUB walks every entry and filters by image extension.
    """
    suffix = Path(src_path).suffix.lower()
    prefix = _OOXML_MEDIA_PREFIX.get(suffix)
    try:
        zf = zipfile.ZipFile(str(src_path))
    except (zipfile.BadZipFile, FileNotFoundError, OSError) as exc:
        if log is not None:
            log(f"  ! Could not open {suffix} for image extraction: {exc}")
        return
    with zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            lower = name.lower()
            if prefix is not None and not lower.startswith(prefix):
                continue
            ext = Path(lower).suffix
            if ext not in _IMAGE_EXTS:
                continue
            try:
                data = zf.read(name)
            except Exception:  # noqa: BLE001 - skip unreadable entry
                continue
            if not data:
                continue
            yield name, data, ext


def extract_zip_document_images_markdown(
    src_path: str | Path,
    *,
    log: Callable[[str], None] | None = None,
) -> str:
    """Return a Markdown section embedding every image in a ZIP-based
    document (.docx/.pptx/.xlsx/.epub) as a base64 ``data:`` URI.

    Returns an empty string when no images are present or the file can't be
    opened. Never raises.
    """
    chunks: list[str] = []
    for _, data, ext in _iter_zip_document_images(src_path, log):
        b64 = base64.b64encode(data).decode("ascii")
        alt = f"image {len(chunks) + 1}"
        chunks.append(f"![{alt}](data:image/{_mime_for_ext(ext)};base64,{b64})")
    if not chunks:
        if log is not None:
            log("  -> no embedded images found to extract")
        return ""
    if log is not None:
        log(f"  -> embedded {len(chunks)} image(s) as base64")
    return "## Embedded images\n\n" + "\n\n".join(chunks)


def extract_zip_document_images_to_files(
    src_path: str | Path,
    output_md_path: str | Path,
    *,
    subfolder: str = DEFAULT_IMAGE_SUBFOLDER,
    log: Callable[[str], None] | None = None,
) -> str:
    """Write every image in a ZIP-based document to ``<md_dir>/<subfolder>/``
    and return a Markdown section linking them with relative paths.

    Filenames are prefixed with the ``.md`` stem so multiple documents can
    share an ``images/`` folder without colliding. The original image bytes
    (and extensions) are preserved — no rasterisation.

    Returns an empty string when no images are present or the file can't be
    opened. Never raises.
    """
    md_path = Path(output_md_path)
    image_dir = md_path.parent / subfolder
    name_prefix = _safe_stem(md_path.stem)

    lines: list[str] = []
    used_names: set[str] = set()
    for entry_name, data, ext in _iter_zip_document_images(src_path, log):
        stem = _safe_stem(Path(entry_name).stem)
        filename = f"{name_prefix}_{stem}{ext}"
        # Two embedded images can share a basename in different folders
        # (rare in OOXML, possible in EPUB). Disambiguate with a counter.
        if filename in used_names:
            counter = 2
            while f"{name_prefix}_{stem}_{counter}{ext}" in used_names:
                counter += 1
            filename = f"{name_prefix}_{stem}_{counter}{ext}"
        used_names.add(filename)

        try:
            image_dir.mkdir(parents=True, exist_ok=True)
            (image_dir / filename).write_bytes(data)
        except Exception as exc:  # noqa: BLE001 - report and skip
            if log is not None:
                log(f"  ! Could not write {filename}: {exc}")
            continue

        alt = f"image {len(lines) + 1}"
        # Markdown links always use forward slashes, even on Windows.
        lines.append(f"![{alt}]({subfolder}/{filename})")

    if not lines:
        if log is not None:
            log("  -> no embedded images found to extract")
        return ""
    if log is not None:
        log(f"  -> extracted {len(lines)} image(s) to {subfolder}/")
    return "## Embedded images\n\n" + "\n\n".join(lines)


# === Unified dispatch ==============================================
# A single entry point per mode that picks the right backend by file
# extension. Keeps the worker thin and the user-facing log message
# consistent across formats.


def _log_unsupported(suffix: str, log: Callable[[str], None] | None) -> str:
    if log is not None:
        log(
            f"  -> image extraction not supported for '{suffix}' files "
            "(supported: .pdf, .docx, .pptx, .xlsx, .epub)"
        )
    return ""


def extract_document_images_markdown(
    src_path: str | Path,
    *,
    log: Callable[[str], None] | None = None,
) -> str:
    """Embed every image in ``src_path`` as a base64 ``data:`` URI."""
    suffix = Path(src_path).suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_images_markdown(src_path, log=log)
    if suffix in _ZIP_DOCUMENT_EXTS:
        return extract_zip_document_images_markdown(src_path, log=log)
    return _log_unsupported(suffix, log)


def extract_document_images_to_files(
    src_path: str | Path,
    output_md_path: str | Path,
    *,
    log: Callable[[str], None] | None = None,
) -> str:
    """Write every image in ``src_path`` to ``<md_dir>/images/`` and return
    a Markdown section linking them."""
    suffix = Path(src_path).suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_images_to_files(src_path, output_md_path, log=log)
    if suffix in _ZIP_DOCUMENT_EXTS:
        return extract_zip_document_images_to_files(
            src_path, output_md_path, log=log,
        )
    return _log_unsupported(suffix, log)


# === Inline base64 / truncated URI → file refs =====================
# MarkItDown's converters embed images directly in the Markdown — but
# in two awkward shapes that both have to be handled here:
#
# 1. **Full** ``data:image/png;base64,<actual-bytes>`` URIs — the bytes are
#    right there in the URI and we can decode and write them straight.
# 2. **Truncated** ``data:image/png;base64...`` placeholders — emitted by
#    mammoth-backed ``.docx`` conversion, where the URI is literally just
#    ``base64...`` (three dots, no bytes). The bytes only live inside the
#    source document's ZIP container.
#
# Both shapes show up in the same document, so one regex covers both via an
# alternation. For (2) we pull the bytes from the source on the fly.
#
# Identical images (SHA-256 of the decoded bytes) share one file — a logo
# that appears 50 times across the document is written once.

_INLINE_IMG_PATTERN = re.compile(
    r"data:image/([A-Za-z0-9.+-]+);base64"
    r"(?:,([A-Za-z0-9+/=\s]+?)(?=[)\s\"'])"  # group 2 = real base64
    r"|\.\.\.)"                              # OR three-dot truncation
)


def _media_sort_key(entry_name: str) -> tuple[int, int, str]:
    """Sort key that orders ``image1.png`` before ``image10.png`` so the
    sequence we hand back matches the order Word numbered them in."""
    stem = Path(entry_name).stem.lower()
    match = re.match(r"(?:.*/)?image(\d+)$", stem)
    if match is not None:
        return (0, int(match.group(1)), "")
    return (1, 0, stem)


def rewrite_inline_images_to_files(
    markdown: str,
    src_path: str | Path,
    output_md_path: str | Path,
    *,
    subfolder: str = DEFAULT_IMAGE_SUBFOLDER,
    log: Callable[[str], None] | None = None,
) -> tuple[str, int]:
    """Replace every inline image reference in ``markdown`` with a relative
    link to a file on disk.

    Handles both full ``data:image/...;base64,<bytes>`` URIs (decoded from
    the URI itself) and the truncated ``data:image/...;base64...``
    placeholders MarkItDown emits for .docx — the latter's bytes are pulled
    from ``src_path`` in source-media order so each placeholder maps to the
    next image the document referenced.

    Returns ``(new_markdown, unique_image_count)``.
    """
    md_path = Path(output_md_path)
    image_dir = md_path.parent / subfolder
    name_prefix = _safe_stem(md_path.stem)

    # Lazily pulled — only built if the markdown contains a truncated
    # placeholder. For PDFs (no inline URIs at all) we never touch the ZIP.
    source_images: list[tuple[str, bytes, str]] | None = None

    def _ensure_source_images() -> list[tuple[str, bytes, str]]:
        nonlocal source_images
        if source_images is not None:
            return source_images
        items = list(_iter_zip_document_images(src_path, log))
        items.sort(key=lambda triple: _media_sort_key(triple[0]))
        source_images = items
        return items

    seen: dict[str, str] = {}  # sha256 hex -> relative link
    state = {"unique": 0, "total": 0, "src_idx": 0}

    def _store(data: bytes, ext_token: str) -> str | None:
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            return seen[digest]
        ext_norm = "." + {"jpeg": "jpg", "tiff": "tif", "svg+xml": "svg"}.get(
            ext_token.lower(), ext_token.lower(),
        )
        candidate_idx = state["unique"] + 1
        filename = f"{name_prefix}_image{candidate_idx}{ext_norm}"
        try:
            image_dir.mkdir(parents=True, exist_ok=True)
            (image_dir / filename).write_bytes(data)
        except Exception as exc:  # noqa: BLE001 - report and skip
            if log is not None:
                log(f"  ! Could not write {filename}: {exc}")
            return None
        state["unique"] = candidate_idx
        relative = f"{subfolder}/{filename}"
        seen[digest] = relative
        return relative

    def _replace(match: re.Match[str]) -> str:
        state["total"] += 1
        ext_from_uri = match.group(1).lower()
        real_b64 = match.group(2)

        if real_b64 is not None:
            # Case 1 — full URI carries the bytes itself.
            try:
                data = base64.b64decode(re.sub(r"\s+", "", real_b64), validate=True)
            except Exception:
                return match.group(0)
            rel = _store(data, ext_from_uri)
            return rel if rel is not None else match.group(0)

        # Case 2 — truncated placeholder. Use the next image from the
        # source ZIP, in document order.
        items = _ensure_source_images()
        if not items:
            # Source has no media (e.g. PDF). Strip the broken placeholder
            # entirely — leaving 'data:image/png;base64...' in the output
            # is strictly worse than removing it.
            return ""
        idx = state["src_idx"]
        state["src_idx"] += 1
        if idx >= len(items):
            # More placeholders than source images — reuse the last one
            # rather than fail. The mismatch is almost always benign
            # (markitdown counting a referenced image twice).
            idx = len(items) - 1
        _, data, ext = items[idx]
        rel = _store(data, ext.lstrip("."))
        return rel if rel is not None else ""

    new_md = _INLINE_IMG_PATTERN.sub(_replace, markdown)

    if state["total"] and log is not None:
        log(
            f"  -> {state['unique']} unique image(s) written to "
            f"{subfolder}/, {state['total']} reference(s) rewritten"
        )
    return new_md, state["unique"]


def rewrite_truncated_uris_to_base64(
    markdown: str,
    src_path: str | Path,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[str, int]:
    """Replace truncated ``data:image/...;base64...`` placeholders with the
    real base64-encoded bytes pulled from ``src_path``.

    Used in *embed* mode for formats (notably .docx) where MarkItDown drops
    the actual image data in favour of a literal ``...`` placeholder.
    Returns ``(new_markdown, references_rewritten)``.
    """
    truncated = re.compile(r"data:image/([A-Za-z0-9.+-]+);base64\.\.\.")
    if not truncated.search(markdown):
        return markdown, 0

    items = list(_iter_zip_document_images(src_path, log))
    items.sort(key=lambda triple: _media_sort_key(triple[0]))
    if not items:
        return markdown, 0

    state = {"idx": 0, "rewritten": 0}

    def _replace(_match: re.Match[str]) -> str:
        if state["idx"] >= len(items):
            i = len(items) - 1
        else:
            i = state["idx"]
            state["idx"] += 1
        _, data, ext = items[i]
        mime = _mime_for_ext(ext.lower())
        b64 = base64.b64encode(data).decode("ascii")
        state["rewritten"] += 1
        return f"data:image/{mime};base64,{b64}"

    new_md = truncated.sub(_replace, markdown)
    if log is not None:
        log(
            f"  -> rewrote {state['rewritten']} truncated placeholder(s) "
            "with real base64 bytes from the source document"
        )
    return new_md, state["rewritten"]
