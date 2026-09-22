"""The files a vault keeps beside its catalog: downloaded media and previews.

The detail page and the `/vault` endpoints ask the same two questions — what did
this vault save for this entry, and what may be served out of that directory —
so both answers live here. A saved file counts as an entry's when its name
contains the entry id, which is the rule the download phase itself works by.
"""

import mimetypes
from collections import namedtuple

from .download import MEDIA_DIR, PREVIEW_DIR, stored_names

# The type a saved file is served as when its name implies nothing better.
MEDIA_FALLBACK_TYPE = "application/octet-stream"
IMAGE_FALLBACK_TYPE = "image/jpeg"

#: The filenames a vault holds for one entry, each `None` when it holds none.
StoredAssets = namedtuple("StoredAssets", "media preview")


def stored_assets(vault, entry_id):
    """The media and preview files `vault` saved for `entry_id`."""
    return StoredAssets(
        matching_name(vault / MEDIA_DIR, entry_id),
        matching_name(vault / PREVIEW_DIR, entry_id),
    )


def matching_name(directory, entry_id):
    """The saved filename in `directory` containing `entry_id`, or `None`.

    More than one file can match a single entry; taking them in name order
    makes the answer the same on every request.
    """
    return next((name for name in sorted(stored_names(directory)) if entry_id in name), None)


def media_asset(directory, filename):
    """The saved media file `filename` as `(path, MIME type)`, if it is there."""
    path = directory / filename
    return (path, guess_type(path, MEDIA_FALLBACK_TYPE)) if path.is_file() else None


def preview_asset(directory, entry_id):
    """The saved preview matching `entry_id` as `(path, MIME type)`."""
    name = matching_name(directory, entry_id)
    if name is None:
        return None
    path = directory / name
    return path, guess_type(path, IMAGE_FALLBACK_TYPE)


def escapes(directory, requested):
    """Whether `requested` leads out of `directory`, as a traversal does."""
    return not (directory / requested).resolve().is_relative_to(directory.resolve())


def guess_type(path, fallback):
    """The MIME type a saved file's name implies, or `fallback`."""
    return mimetypes.guess_type(path.name)[0] or fallback
