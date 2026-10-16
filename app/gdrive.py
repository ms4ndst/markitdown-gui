"""Use a Google Drive folder as the conversion source.

The reverse of Confluence L33ch's "Upload to Google Docs": that mirrors a
local Markdown tree into a Drive folder, turning every ``.md`` into a Google
Doc and every subdirectory into a Drive folder. This module walks such a
Drive folder (or any other) and feeds its contents back through the normal
conversion pipeline, so the output directory gets the same folder tree with
one ``.md`` per Doc.

* Google Docs / Sheets / Slides are exported as DOCX / XLSX / PPTX — the
  formats MarkItDown already converts, so tables, headings, images and every
  post-processing option behave exactly as for local Office files.
* Uploaded files (PDF, DOCX, images, …) with a supported extension are
  downloaded as-is; anything else is skipped and logged.
* Links between Docs (``docs.google.com/document/d/<id>/…``) are rewritten
  to relative links between the converted ``.md`` files, undoing the link
  rewriting L33ch does on upload.

Access is read-only (``drive.readonly``). The Google client libraries are
imported lazily so the rest of the app runs without them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from PySide6.QtCore import QObject, Signal


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

TOKEN_FILENAME = "google-token.json"

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
GOOGLE_APPS_PREFIX = "application/vnd.google-apps."

# Google-native type -> (export MIME type, extension MarkItDown recognises).
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}

KIND_LABELS = {
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
}

INSTALL_HINT = (
    "Install the Google client libraries with: "
    "pip install google-api-python-client google-auth-oauthlib"
)

# Retries for rate limits (403 userRateLimitExceeded / 429) and 5xx, with
# the client library's own exponential backoff.
RETRIES = 5

_FOLDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
# Characters Windows refuses in a filename. Sanitised on every platform so
# an output folder stays portable — same rule Confluence L33ch uses.
_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
# Markdown link / image targets: ``](url)`` or ``](url "title")``.
_MD_LINK_RE = re.compile(r"\]\((<?)([^)\s>]+)(>?)((?:\s+\"[^\"]*\")?)\)")
_DRIVE_ID_PATH_RE = re.compile(
    r"/(?:document|spreadsheets|presentation|file|drawings|forms)"
    r"(?:/u/\d+)?/d/([A-Za-z0-9_-]{10,})"
)


class DriveError(RuntimeError):
    """A failure worth showing the user verbatim."""


# --- pure helpers ------------------------------------------------------


def parse_folder_id(text: str) -> str:
    """Extract a Drive folder ID from a pasted URL, or accept a bare ID.

    Handles ``/drive/folders/<id>``, ``/drive/u/1/folders/<id>``,
    ``/drive/folders/<id>?usp=sharing`` and ``open?id=<id>``. Returns ``""``
    for anything else, which the GUI turns into a message.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if "://" not in text:
        return text if _FOLDER_ID_RE.match(text) else ""
    parts = urlsplit(text)
    segments = [s for s in parts.path.split("/") if s]
    if "folders" in segments:
        index = segments.index("folders")
        if index + 1 < len(segments) and _FOLDER_ID_RE.match(segments[index + 1]):
            return segments[index + 1]
    ids = parse_qs(parts.query).get("id")
    if ids and _FOLDER_ID_RE.match(ids[0]):
        return ids[0]
    return ""


def drive_id_from_url(url: str) -> str:
    """The Drive file ID a Docs / Sheets / Slides / Drive URL points at.

    Also unwraps Google's ``https://www.google.com/url?q=<target>`` redirect
    that Docs puts around some links. Returns ``""`` for anything else.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host = parts.netloc.lower()
    if host in ("www.google.com", "google.com") and parts.path == "/url":
        target = parse_qs(parts.query).get("q")
        return drive_id_from_url(target[0]) if target else ""
    if not (host.endswith("docs.google.com") or host.endswith("drive.google.com")):
        return ""
    match = _DRIVE_ID_PATH_RE.search(parts.path)
    if match:
        return match.group(1)
    ids = parse_qs(parts.query).get("id")
    if ids and _FOLDER_ID_RE.match(ids[0]):
        return ids[0]
    return ""


def sanitize_name(name: str) -> str:
    """A Drive item name made safe as a file or folder name on any OS."""
    cleaned = _INVALID_CHARS_RE.sub("_", name).strip().rstrip(". ")
    if not cleaned:
        cleaned = "_"
    if cleaned.split(".", 1)[0].upper() in _RESERVED_NAMES:
        cleaned = "_" + cleaned
    return cleaned


def _unique(name: str, taken: set[str]) -> str:
    """``name``, or ``name (2)``, ``name (3)`` … — case-insensitively unique."""
    candidate, n = name, 2
    while candidate.lower() in taken:
        candidate = f"{name} ({n})"
        n += 1
    taken.add(candidate.lower())
    return candidate


def rewrite_drive_links(
    markdown: str,
    destination: Path,
    targets: dict[str, Path],
) -> tuple[str, int]:
    """Point links at other converted Drive items to their local ``.md``.

    ``targets`` maps a Drive file ID to the output path it is converted to.
    Each link resolving to one of them becomes a relative path from
    ``destination``'s folder; a ``#fragment`` is dropped, since Docs'
    ``#heading=h.…`` anchors mean nothing in Markdown. Returns the text and
    the number of links rewritten.
    """
    if not targets or "google.com" not in markdown:
        return markdown, 0
    count = 0

    def repl(match: re.Match) -> str:
        nonlocal count
        url = match.group(2)
        file_id = drive_id_from_url(url)
        target = targets.get(file_id) if file_id else None
        if target is None:
            return match.group(0)
        rel = os.path.relpath(target, destination.parent).replace(os.sep, "/")
        # Spaces would end the link target; angle brackets keep it intact.
        rel = f"<{rel}>" if " " in rel else rel
        count += 1
        return f"]({rel}{match.group(4)})"

    return _MD_LINK_RE.sub(repl, markdown), count


@dataclass
class DriveEntry:
    """One convertible file found under the chosen Drive folder."""

    file_id: str
    name: str            # the item's name in Drive
    mime_type: str
    rel_dir: str         # POSIX path of its folder, relative to the root; "" = root
    stem: str            # sanitised, unique-per-folder name for the output .md
    extension: str       # extension of the downloaded / exported file

    @property
    def is_google_native(self) -> bool:
        return self.mime_type in EXPORT_FORMATS

    @property
    def kind(self) -> str:
        return KIND_LABELS.get(self.mime_type, self.extension.lstrip(".").upper())

    @property
    def rel_path(self) -> str:
        """``rel_dir/stem`` — where the converted ``.md`` goes, minus suffix."""
        return str(PurePosixPath(self.rel_dir) / self.stem) if self.rel_dir else self.stem

    def display(self) -> str:
        return f"Google Drive › {self.rel_dir + '/' if self.rel_dir else ''}{self.name}  ({self.kind})"

    def to_dict(self) -> dict[str, str]:
        return {
            "file_id": self.file_id, "name": self.name, "mime_type": self.mime_type,
            "rel_dir": self.rel_dir, "stem": self.stem, "extension": self.extension,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "DriveEntry":
        return cls(**{k: data[k] for k in (
            "file_id", "name", "mime_type", "rel_dir", "stem", "extension"
        )})


# --- Drive access ------------------------------------------------------


def _list_kwargs() -> dict:
    return {"supportsAllDrives": True, "includeItemsFromAllDrives": True}


def list_drive_tree(
    service: Any,
    folder_id: str,
    supported_extensions: set[str],
    log: Callable[[str], None] = lambda _msg: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[str, list[DriveEntry]]:
    """Walk ``folder_id`` recursively; return ``(root name, entries)``.

    Folder names are sanitised and made unique per parent, as are the output
    stems, so two Drive items called "Notes" never write the same ``.md``.
    Shortcuts and Google types with no Office export (Forms, Drawings,
    Sites…) are skipped with a log line.
    """
    files = service.files()
    try:
        root = files.get(
            fileId=folder_id, fields="id,name,mimeType", supportsAllDrives=True,
        ).execute(num_retries=RETRIES)
    except Exception as exc:  # noqa: BLE001 — HttpError and transport errors
        raise DriveError(
            f"Cannot open the Drive folder {folder_id}: {exc}. Check the URL "
            "and that the signed-in account can view the folder."
        ) from exc
    if root.get("mimeType") != FOLDER_MIME:
        raise DriveError(f"'{root.get('name')}' is not a folder.")

    entries: list[DriveEntry] = []
    skipped = 0
    # Breadth-first so entries come out folder by folder, in name order.
    queue: list[tuple[str, str]] = [(folder_id, "")]
    while queue:
        if cancelled():
            break
        parent_id, rel_dir = queue.pop(0)
        children = _list_children(files, parent_id)
        taken_dirs: set[str] = set()
        taken_stems: set[str] = set()
        for child in children:
            mime = child.get("mimeType", "")
            name = child.get("name", "")
            where = f"{rel_dir}/{name}" if rel_dir else name
            if mime == FOLDER_MIME:
                sub = _unique(sanitize_name(name), taken_dirs)
                queue.append((child["id"], f"{rel_dir}/{sub}" if rel_dir else sub))
                continue
            if mime in EXPORT_FORMATS:
                extension = EXPORT_FORMATS[mime][1]
                stem = sanitize_name(name)
            elif mime.startswith(GOOGLE_APPS_PREFIX):
                kind = "shortcut" if mime == SHORTCUT_MIME else mime.rsplit(".", 1)[-1]
                log(f"  skipped {where} ({kind} — no Markdown conversion)")
                skipped += 1
                continue
            else:
                extension = Path(name).suffix.lower()
                if extension not in supported_extensions:
                    skipped += 1
                    continue
                stem = sanitize_name(Path(name).stem)
            entries.append(DriveEntry(
                file_id=child["id"], name=name, mime_type=mime, rel_dir=rel_dir,
                stem=_unique(stem, taken_stems), extension=extension,
            ))
    if skipped:
        log(f"Skipped {skipped} Drive item(s) that cannot be converted.")
    return root.get("name", ""), entries


def _list_children(files: Any, parent_id: str) -> list[dict]:
    out: list[dict] = []
    token = None
    while True:
        resp = files.list(
            q=f"'{parent_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,mimeType)",
            orderBy="folder,name",
            pageSize=1000,
            pageToken=token,
            **_list_kwargs(),
        ).execute(num_retries=RETRIES)
        out.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return out


def download_entry(service: Any, creds: Any, entry: DriveEntry, target: Path) -> Path:
    """Download (or export) ``entry`` to ``target``; returns ``target``.

    ``files.export`` refuses anything whose export exceeds 10 MB, which a Doc
    full of images easily does; those fall back to the file's
    ``exportLinks``, fetched with the same credentials.
    """
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload

    files = service.files()
    target.parent.mkdir(parents=True, exist_ok=True)
    if entry.is_google_native:
        export_mime = EXPORT_FORMATS[entry.mime_type][0]
        request = files.export_media(fileId=entry.file_id, mimeType=export_mime)
    else:
        request = files.get_media(fileId=entry.file_id, supportsAllDrives=True)
    try:
        with target.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request, chunksize=8 * 1024 * 1024)
            done = False
            while not done:
                _status, done = downloader.next_chunk(num_retries=RETRIES)
    except HttpError as exc:
        if not entry.is_google_native or "exportSizeLimitExceeded" not in str(exc):
            raise
        _download_export_link(files, creds, entry, target)
    return target


def _download_export_link(files: Any, creds: Any, entry: DriveEntry, target: Path) -> None:
    from google.auth.transport.requests import AuthorizedSession

    export_mime = EXPORT_FORMATS[entry.mime_type][0]
    meta = files.get(
        fileId=entry.file_id, fields="exportLinks", supportsAllDrives=True,
    ).execute(num_retries=RETRIES)
    url = (meta.get("exportLinks") or {}).get(export_mime)
    if not url:
        raise DriveError(f"'{entry.name}' is too large to export as {entry.extension}.")
    with AuthorizedSession(creds).get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with target.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                handle.write(chunk)


# --- authentication ----------------------------------------------------


def token_path() -> Path:
    from .config import config_path

    return config_path().parent / TOKEN_FILENAME


def missing_dependency() -> str:
    """The name of a missing optional library, or ``""`` when all are there."""
    for module in ("googleapiclient", "google_auth_oauthlib"):
        try:
            __import__(module)
        except ImportError:
            return module
    return ""


def load_credentials(path: Path | None = None):
    """Saved credentials, refreshed if needed; None when not signed in."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = path or token_path()
    if not path.is_file():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, OSError):
        return None
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001 — RefreshError, transport
            raise DriveError(
                f"The saved Google sign-in no longer works ({exc}). "
                "Click 'Sign in' again."
            ) from exc
        _save_token(creds, path)
        return creds
    return None


def _save_token(creds, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    # Created owner-only: it holds a refresh token.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    tmp.replace(path)


def sign_out(path: Path | None = None) -> None:
    path = path or token_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def build_service(creds):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def connect():
    """``(service, creds)`` for the signed-in account, or raise DriveError."""
    missing = missing_dependency()
    if missing:
        raise DriveError(f"Missing dependency: {missing}. {INSTALL_HINT}")
    creds = load_credentials()
    if creds is None:
        raise DriveError("Not signed in to Google. Click 'Sign in…' first.")
    return build_service(creds), creds


def account_email(service) -> str:
    about = service.about().get(fields="user(emailAddress)").execute(
        num_retries=RETRIES
    )
    return (about.get("user") or {}).get("emailAddress", "")


class SignInWorker(QObject):
    """Runs the browser OAuth flow off the GUI thread.

    ``run_local_server`` blocks until the browser redirects back to a
    loopback port, which can take as long as the user takes to click — so
    the GUI runs this on a daemon thread rather than a QThread.
    """

    finished = Signal(str, str)   # email ("" on failure), error message

    def __init__(self, client_secrets: Path) -> None:
        super().__init__()
        self._client_secrets = client_secrets

    def run(self) -> None:
        try:
            missing = missing_dependency()
            if missing:
                raise DriveError(f"Missing dependency: {missing}. {INSTALL_HINT}")
            from google_auth_oauthlib.flow import InstalledAppFlow

            flow = InstalledAppFlow.from_client_secrets_file(
                str(self._client_secrets), SCOPES
            )
            creds = flow.run_local_server(
                port=0, open_browser=True, timeout_seconds=300,
                authorization_prompt_message="",
                success_message=(
                    "Signed in. You can close this tab and return to MarkItDown."
                ),
            )
            _save_token(creds, token_path())
            email = account_email(build_service(creds))
        except Exception as exc:  # noqa: BLE001
            self.finished.emit("", f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(email or "(signed in)", "")


class DriveListWorker(QObject):
    """Lists a Drive folder tree off the GUI thread."""

    log = Signal(str)
    # root folder name, list of DriveEntry.to_dict(), error message
    finished = Signal(str, list, str)

    def __init__(self, folder_id: str, supported_extensions: set[str]) -> None:
        super().__init__()
        self._folder_id = folder_id
        self._extensions = supported_extensions

    def run(self) -> None:
        try:
            service, _creds = connect()
            name, entries = list_drive_tree(
                service, self._folder_id, self._extensions, log=self.log.emit,
            )
        except Exception as exc:  # noqa: BLE001
            self.finished.emit("", [], str(exc))
            return
        self.finished.emit(name, [e.to_dict() for e in entries], "")
