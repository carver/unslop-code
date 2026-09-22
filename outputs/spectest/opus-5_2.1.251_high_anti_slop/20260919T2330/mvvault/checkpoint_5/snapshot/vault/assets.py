"""Serving the files a vault has downloaded: its media and its preview images.

A media request names a stored filename, a preview request names an entry id
and gets the saved image whose filename holds it. Both stay inside the vault's
own ``media/`` and ``previews/`` directories: a request segment that is not a
plain filename never reaches the filesystem.
"""

import mimetypes
from pathlib import Path

from .downloads import MEDIA_DIR, PARTIAL_SUFFIX, PREVIEW_DIR
from .viewer import MEDIA_ROUTE, PREVIEW_ROUTE

#: Served when a stored file's extension names no known type.
FALLBACK_TYPE = "application/octet-stream"


def locate(name, kind, target):
    """Path of the asset a static route addresses, or ``None`` when the vault has none."""
    if kind == MEDIA_ROUTE:
        media = Path(name) / MEDIA_DIR / target
        return media if _is_stored(media) else None
    if kind == PREVIEW_ROUTE:
        return _matching(Path(name) / PREVIEW_DIR, target)
    return None


def content_type(path):
    """MIME type a stored asset is served with, read from its extension."""
    return mimetypes.guess_type(path.name)[0] or FALLBACK_TYPE


def _is_stored(path):
    """Tell whether a path is a fully downloaded file; an interrupted one counts as absent."""
    return path.is_file() and path.suffix != PARTIAL_SUFFIX


def _matching(directory, entry_id):
    """First saved file in ``directory`` whose name contains ``entry_id``, in name order."""
    if not directory.is_dir():
        return None
    found = sorted(
        path for path in directory.iterdir() if entry_id in path.name and _is_stored(path)
    )
    return found[0] if found else None
