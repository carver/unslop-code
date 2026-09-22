"""Serving the files a vault has downloaded, under `/vault/<name>/...`.

Media is asked for by the saved filename a detail page found; a preview is asked
for by entry id, because the extension a preview was saved under depends on what
the source sent. Neither lookup may leave the directory it belongs to, so the
media filename is resolved against `media/` and refused if it lands anywhere
else, while a preview is only ever one of the names already in `previews/`.
"""

import mimetypes
from dataclasses import dataclass

from .vault import CATALOG_FILENAME, MEDIA_DIRNAME, PREVIEWS_DIRNAME
from .viewer import VaultNotFound, matching_file, vault_path

#: Content types for an extension `mimetypes` cannot place. The preview endpoint
#: is specified to answer with an image type, so that is what it falls back to.
DEFAULT_MEDIA_TYPE = "application/octet-stream"
DEFAULT_IMAGE_TYPE = "image/png"


class UnsafePath(Exception):
    """A request that tried to reach outside the directory it named."""


@dataclass(frozen=True)
class Asset:
    """One file, ready to be written to the wire."""

    content: bytes
    content_type: str


def media_asset(root, name, filename):
    """`<vault>/media/<filename>`, or None when the vault has no such file."""
    path = _within(_directory(root, name) / MEDIA_DIRNAME, filename)
    return _read(path, DEFAULT_MEDIA_TYPE)


def preview_asset(root, name, entry_id):
    """The preview whose saved filename contains `entry_id`, or None."""
    directory = _directory(root, name) / PREVIEWS_DIRNAME
    match = matching_file(directory, entry_id)
    return _read(directory / match, DEFAULT_IMAGE_TYPE) if match else None


#: The `/vault/<name>/<kind>/<target>` endpoints, by the kind they serve.
ASSET_READERS = {"media": media_asset, "preview": preview_asset}


def _directory(root, name):
    """The directory of a vault that exists, or VaultNotFound if none does."""
    path = vault_path(root, name)
    if not (path / CATALOG_FILENAME).is_file():
        raise VaultNotFound(f"{name!r} is not a vault")
    return path


def _within(directory, filename):
    """`filename` resolved inside `directory`, refusing anything that escapes it."""
    path = (directory / filename).resolve()
    if directory.resolve() not in path.parents:
        raise UnsafePath(f"{filename!r} does not name a file in {directory.name}/")
    return path


def _read(path, default_type):
    """The file as an asset, or None when it is not there to be read."""
    if not path.is_file():
        return None
    return Asset(path.read_bytes(), mimetypes.guess_type(path.name)[0] or default_type)
