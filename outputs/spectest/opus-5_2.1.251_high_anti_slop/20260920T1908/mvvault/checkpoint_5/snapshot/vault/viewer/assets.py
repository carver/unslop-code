"""The stored vault files the viewer reads about and serves.

Downloads are named after the entry they belong to, so an entry owns the saved
files whose names carry its id — which is also how a listing decides that an
entry has its media on disk. Only plain file names are served: a request whose
name carries a path separator is refused rather than followed, so nothing
outside ``media/`` and ``previews/`` is reachable.
"""

import mimetypes
from pathlib import Path

from ..download import MEDIA_DIR, PREVIEW_DIR

DEFAULT_TYPE = "application/octet-stream"


def is_plain_name(name: str) -> bool:
    """Whether a decoded path segment names one file here and nothing above it."""
    return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name


def media_names(vault_dir: Path) -> list[str]:
    """The names of the media files a vault has downloaded, in name order."""
    return _stored_names(vault_dir / MEDIA_DIR)


def media_name(vault_dir: Path, entry_id: str) -> str | None:
    """The media file downloaded for one entry, or ``None`` when it has none."""
    return _named_after(media_names(vault_dir), entry_id)


def preview_name(vault_dir: Path, entry_id: str) -> str | None:
    """The preview image downloaded for one entry, or ``None`` when it has none."""
    return _named_after(_stored_names(vault_dir / PREVIEW_DIR), entry_id)


def media_asset(vault_dir: Path, filename: str) -> Path | None:
    """The media file a ``/vault/<name>/media/<file>`` request names, if it is stored."""
    return _stored_file(vault_dir / MEDIA_DIR / filename)


def preview_asset(vault_dir: Path, entry_id: str) -> Path | None:
    """The preview image a ``/vault/<name>/preview/<id>`` request names, if it is stored.

    A preview is asked for by entry, not by file name, so the saved image
    naming that entry is the one served.
    """
    name = preview_name(vault_dir, entry_id)
    return _stored_file(vault_dir / PREVIEW_DIR / name) if name else None


def content_type(filename: str) -> str:
    """The MIME type a saved file is served with, read from its extension.

    Downloads take the extension their content type implied, so the type a
    file was fetched as is the type it is served as.
    """
    return mimetypes.guess_type(filename)[0] or DEFAULT_TYPE


def _stored_names(directory: Path) -> list[str]:
    """The file names of one vault directory, or none when it was never created."""
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.iterdir() if path.is_file())


def _named_after(names: list[str], entry_id: str) -> str | None:
    """The first saved name carrying ``entry_id``, which is the file of that entry."""
    return next((name for name in names if entry_id in name), None)


def _stored_file(path: Path) -> Path | None:
    return path if path.is_file() else None
