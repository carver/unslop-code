"""The media and preview files a vault stores, as the viewer finds and serves them.

A saved file belongs to an entry when the entry's `id` appears anywhere in the
file's name, which is the same rule the download phase's naming produces. Files
are only ever looked up by a name the asset directory itself lists, so a request
carrying a traversal sequence resolves to nothing rather than to a file outside
`media/` or `previews/`.
"""

import mimetypes
from pathlib import Path

from .download import MEDIA_DIR, PREVIEW_DIR

#: Content types used for a stored file whose own name does not reveal one.
MEDIA_TYPE = "application/octet-stream"
IMAGE_TYPE = "image/jpeg"


def media_name(name, entry_id):
    """The saved media file matching `entry_id`, or `None` when the vault has none."""
    return _match(Path(name) / MEDIA_DIR, entry_id)


def preview_name(name, entry_id):
    """The saved preview file matching `entry_id`, or `None` when the vault has none."""
    return _match(Path(name) / PREVIEW_DIR, entry_id)


def downloaded_ids(name, entry_ids):
    """Which of `entry_ids` have a media file saved in the vault."""
    stored = _names(Path(name) / MEDIA_DIR)
    return {entry_id for entry_id in entry_ids if any(entry_id in filename for filename in stored)}


def stored_media(name, filename):
    """The `(bytes, content type)` of `<vault>/media/<filename>`, or `None` when absent."""
    directory = Path(name) / MEDIA_DIR
    return _read(directory, filename, MEDIA_TYPE) if filename in _names(directory) else None


def stored_preview(name, entry_id):
    """The `(bytes, content type)` of the preview matching `entry_id`, or `None`."""
    directory = Path(name) / PREVIEW_DIR
    filename = _match(directory, entry_id)
    return _read(directory, filename, IMAGE_TYPE) if filename else None


def _read(directory, filename, default_type):
    """One stored file, typed from its own name wherever that name says enough."""
    return (directory / filename).read_bytes(), mimetypes.guess_type(filename)[0] or default_type


def _match(directory, entry_id):
    """The first saved name containing `entry_id`; names are sorted, so it is stable."""
    return next((filename for filename in _names(directory) if entry_id in filename), None)


def _names(directory):
    """The file names directly inside an asset directory, sorted, `[]` when it has none."""
    return sorted(path.name for path in directory.iterdir() if path.is_file()) if directory.is_dir() else []
