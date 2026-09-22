"""The files the `/vault` static endpoints serve, resolved safely.

A name taken from a request is only ever accepted when it lands directly inside
the vault's asset directory, so a request carrying a traversal sequence resolves
to nothing instead of to a file the viewer was never asked to publish.
"""

import mimetypes
from dataclasses import dataclass
from pathlib import Path

from mvaultlib.downloads import MEDIA_DIR, PREVIEW_DIR, matching_asset, stored_asset_names

#: Served for a stored file whose extension implies no type of its own.
FALLBACK_MEDIA_TYPE = "application/octet-stream"
FALLBACK_IMAGE_TYPE = "image/jpeg"


@dataclass(frozen=True)
class Asset:
    """A stored file one static endpoint serves, and the type it serves it as."""

    path: Path
    content_type: str


def child_path(directory, name):
    """The path of `name` directly inside `directory`, or None when it escapes.

    Only a plain name resolves: anything carrying a separator or a traversal
    sequence lands somewhere other than `directory` and is refused.
    """
    candidate = directory / name
    return candidate if candidate.parent == directory else None


def media_asset(vault_path, filename):
    """The media file `/vault/<name>/media/<file>` names, or None when absent."""
    target = child_path(vault_path / MEDIA_DIR, filename)
    if target is None or not target.is_file():
        return None
    return Asset(target, _content_type(target, FALLBACK_MEDIA_TYPE))


def preview_asset(vault_path, entry_id):
    """The stored preview whose file name contains `entry_id`, or None."""
    directory = vault_path / PREVIEW_DIR
    match = matching_asset(entry_id, stored_asset_names(directory))
    if match is None:
        return None
    return Asset(directory / match, _content_type(directory / match, FALLBACK_IMAGE_TYPE))


def _content_type(path, fallback):
    """The MIME type a stored file's extension implies."""
    return mimetypes.guess_type(path.name)[0] or fallback
