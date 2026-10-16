"""Tests for the Google Drive source in ``app.gdrive`` and its use by the
conversion worker. A fake Drive service stands in for the real API."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import gdrive
from app.gdrive import (
    DriveEntry,
    drive_id_from_url,
    list_drive_tree,
    parse_folder_id,
    rewrite_drive_links,
    sanitize_name,
)
from app.worker import ConversionItem, ConversionWorker

DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"
FOLDER = gdrive.FOLDER_MIME
FOLDER_ID = "rootFolder1234"


class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self, num_retries=0):
        return self._result


class FakeFiles:
    """``files()`` resource over an in-memory ``{id: (name, mime, parent)}``."""

    def __init__(self, items: dict[str, tuple[str, str, str | None]]):
        self._items = items

    def get(self, fileId, **_kw):
        name, mime, _parent = self._items[fileId]
        return _Call({"id": fileId, "name": name, "mimeType": mime})

    def list(self, q, **_kw):
        parent = q.split("'")[1]
        children = [
            {"id": fid, "name": name, "mimeType": mime}
            for fid, (name, mime, p) in self._items.items() if p == parent
        ]
        children.sort(key=lambda c: (c["mimeType"] != FOLDER, c["name"]))
        return _Call({"files": children})


class FakeService:
    def __init__(self, items):
        self._files = FakeFiles(items)

    def files(self):
        return self._files


# A tree shaped like a Confluence L33ch upload: a page with children becomes
# a folder holding a Doc of the same name plus the child Docs.
TREE = {
    FOLDER_ID: ("Space", FOLDER, None),
    "readme0000001": ("README", DOC, FOLDER_ID),
    "guideFolder01": ("Guide", FOLDER, FOLDER_ID),
    "guideDoc00001": ("Guide", DOC, "guideFolder01"),
    "installDoc001": ("Install: Linux/Windows", DOC, "guideFolder01"),
    "budgetSheet01": ("Budget", SHEET, "guideFolder01"),
    "dupeDoc000001": ("Notes", DOC, FOLDER_ID),
    "dupeDoc000002": ("Notes", DOC, FOLDER_ID),
    "formItem00001": ("Survey", "application/vnd.google-apps.form", FOLDER_ID),
    "pdfFile000001": ("Spec.pdf", "application/pdf", FOLDER_ID),
    "binFile000001": ("tool.exe", "application/octet-stream", FOLDER_ID),
}


def _entries():
    return list_drive_tree(FakeService(TREE), FOLDER_ID, {".pdf", ".docx"})


def test_parse_folder_id_variants():
    assert parse_folder_id("https://drive.google.com/drive/folders/1AbCdEfGhIjK?usp=sharing") == "1AbCdEfGhIjK"
    assert parse_folder_id("https://drive.google.com/drive/u/1/folders/1AbCdEfGhIjK") == "1AbCdEfGhIjK"
    assert parse_folder_id("https://drive.google.com/open?id=1AbCdEfGhIjK") == "1AbCdEfGhIjK"
    assert parse_folder_id("1AbCdEfGhIjK") == "1AbCdEfGhIjK"
    assert parse_folder_id("not a folder") == ""


def test_drive_id_from_url_variants():
    assert drive_id_from_url("https://docs.google.com/document/d/abcDEF123456/edit#heading=h.x") == "abcDEF123456"
    assert drive_id_from_url("https://docs.google.com/spreadsheets/u/0/d/abcDEF123456/edit") == "abcDEF123456"
    assert drive_id_from_url("https://drive.google.com/file/d/abcDEF123456/view") == "abcDEF123456"
    assert drive_id_from_url(
        "https://www.google.com/url?q=https://docs.google.com/document/d/abcDEF123456/edit&sa=D"
    ) == "abcDEF123456"
    assert drive_id_from_url("https://example.com/document/d/abcDEF123456") == ""


def test_sanitize_name():
    assert sanitize_name("Install: Linux/Windows") == "Install_ Linux_Windows"
    assert sanitize_name("CON") == "_CON"
    assert sanitize_name("trailing. ") == "trailing"
    assert sanitize_name("") == "_"


def test_tree_mirrors_drive_folders():
    root, entries = _entries()
    assert root == "Space"
    paths = {e.file_id: (e.rel_path, e.extension) for e in entries}
    assert paths["readme0000001"] == ("README", ".docx")
    # The page's own Doc sits inside the folder of the same name.
    assert paths["guideDoc00001"] == ("Guide/Guide", ".docx")
    assert paths["installDoc001"] == ("Guide/Install_ Linux_Windows", ".docx")
    assert paths["budgetSheet01"] == ("Guide/Budget", ".xlsx")
    assert paths["pdfFile000001"] == ("Spec", ".pdf")
    # Same-named Docs in one folder get distinct output names.
    assert {paths["dupeDoc000001"][0], paths["dupeDoc000002"][0]} == {"Notes", "Notes (2)"}
    # Forms and unsupported uploads are skipped.
    assert "formItem00001" not in paths and "binFile000001" not in paths


def test_entry_round_trips_through_dict():
    _root, entries = _entries()
    for entry in entries:
        assert DriveEntry.from_dict(entry.to_dict()) == entry


def test_rewrite_drive_links_to_relative_md(tmp_path):
    out = tmp_path / "out"
    targets = {
        "guideDoc00001": out / "Guide" / "Guide.md",
        "installDoc001": out / "Guide" / "Install guide.md",
    }
    md = (
        "See [the guide](https://docs.google.com/document/d/guideDoc00001/edit#heading=h.1) "
        "and [install](https://docs.google.com/document/d/installDoc001/edit \"Install\"). "
        "[External](https://docs.google.com/document/d/someOtherDoc1/edit) stays."
    )
    text, count = rewrite_drive_links(md, out / "README.md", targets)
    assert count == 2
    assert "[the guide](Guide/Guide.md)" in text
    assert '[install](<Guide/Install guide.md> "Install")' in text
    assert "someOtherDoc1/edit" in text

    text, _ = rewrite_drive_links(md, out / "Guide" / "Install guide.md", targets)
    assert "[the guide](Guide.md)" in text


# --- worker integration ----------------------------------------------------


def _long_markdown(title: str) -> str:
    lines = [f"# {title}", ""]
    for n in range(1, 60):
        lines += [f"## Section {n}", ""] + [f"Body line {n}.{k}" for k in range(8)] + [""]
    return "\n".join(lines)


def _run(items, **kwargs):
    worker = ConversionWorker(items, overwrite=True, **kwargs)
    logs: list[str] = []
    result: list[tuple[int, int]] = []
    worker.log.connect(logs.append)
    worker.finished.connect(lambda s, f: result.append((s, f)))
    worker.run()
    return result[0], logs


def test_per_item_index_override(tmp_path):
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    a, b = src / "a.md", src / "sub" / "b.md"
    a.write_text(_long_markdown("A"), encoding="utf-8")
    b.write_text(_long_markdown("B"), encoding="utf-8")
    out = tmp_path / "out"
    items = [
        ConversionItem(a, out / "a.md", generate_index=True),
        ConversionItem(b, out / "sub" / "b.md", generate_index=False),
    ]
    (success, failure), _logs = _run(items, generate_index=False)
    assert (success, failure) == (2, 0)
    assert (out / "a.index.md").is_file()
    assert not (out / "sub" / "b.index.md").exists()


def test_drive_items_are_fetched_converted_and_relinked(tmp_path, monkeypatch):
    out = tmp_path / "out"
    readme = DriveEntry("readme0000001", "README", DOC, "", "README", ".md")
    guide = DriveEntry("guideDoc00001", "Guide", DOC, "Guide", "Guide", ".md")
    bodies = {
        "readme0000001": "# Home\n\nRead [the guide](https://docs.google.com/document/d/guideDoc00001/edit).\n",
        "guideDoc00001": "# Guide\n\nBack [home](https://docs.google.com/document/d/readme0000001/edit).\n",
    }
    fetched: list[str] = []

    def fake_download(_service, _creds, entry, target):
        fetched.append(entry.file_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(bodies[entry.file_id], encoding="utf-8")
        return target

    monkeypatch.setattr(gdrive, "connect", lambda: (object(), object()))
    monkeypatch.setattr(gdrive, "download_entry", fake_download)

    items = [
        ConversionItem(Path("README.md"), out / "README.md", drive=readme),
        ConversionItem(Path("Guide.md"), out / "Guide" / "Guide.md", drive=guide),
    ]
    (success, failure), logs = _run(items)
    assert (success, failure) == (2, 0), logs
    assert fetched == ["readme0000001", "guideDoc00001"]
    assert "[the guide](Guide/Guide.md)" in (out / "README.md").read_text(encoding="utf-8")
    assert "[home](../README.md)" in (out / "Guide" / "Guide.md").read_text(encoding="utf-8")
    assert any("Google Drive › Guide/Guide" in line for line in logs)


def test_drive_sign_in_missing_fails_cleanly(tmp_path, monkeypatch):
    def not_signed_in():
        raise gdrive.DriveError("Not signed in to Google.")

    monkeypatch.setattr(gdrive, "connect", not_signed_in)
    entry = DriveEntry("readme0000001", "README", DOC, "", "README", ".docx")
    items = [ConversionItem(Path("README.docx"), tmp_path / "README.md", drive=entry)]
    (success, failure), logs = _run(items)
    assert (success, failure) == (0, 1)
    assert any("Not signed in" in line for line in logs)
