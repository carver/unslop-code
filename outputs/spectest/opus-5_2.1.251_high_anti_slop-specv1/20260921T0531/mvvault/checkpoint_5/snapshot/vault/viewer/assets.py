"""The stored files of a vault that the viewer serves for its detail pages.

A detail page plays the media file the vault downloaded and shows the preview
image beside it, both from the vault's own directories. Media is asked for by
the name it is stored under, a preview by the id of the entry it belongs to,
and nothing is served that is not one of the finished files already there — so
a request cannot reach past ``media/`` or ``previews/`` however it is spelled.
"""

import mimetypes
from collections import namedtuple
from pathlib import Path

from .. import links, media

#: One file to send: where it lies and the content type to send it as.
Asset = namedtuple("Asset", "path content_type")

DIRECTORIES = {
    links.MEDIA_KIND: media.MEDIA_DIRECTORY,
    links.PREVIEW_KIND: media.PREVIEW_DIRECTORY,
}
#: Type a file of this kind is served as when its name names no other.
DEFAULT_TYPES = {
    links.MEDIA_KIND: "application/octet-stream",
    links.PREVIEW_KIND: "image/jpeg",
}


def names_one_file(requested):
    """Whether ``requested`` names a single file rather than a path elsewhere.

    The unquoted segment of a request may hold separators and traversal steps;
    one that does is not a file name and is refused rather than resolved.
    """
    return requested not in (".", "..") and requested == Path(requested).name


def locate(root, name, kind, requested):
    """The asset of the vault ``name`` this request asks for, or ``None``.

    Media matches the stored name exactly; a preview matches the stored name
    that holds the requested entry id, which is how downloads name them.
    """
    vault = Path(root) / name
    directory = DIRECTORIES[kind]
    stored = media.stored_names(vault, directory)
    found = requested if kind == links.MEDIA_KIND else media.stored_file(requested, stored)
    if found not in stored:
        return None
    return Asset(vault / directory / found, _content_type(kind, found))


def _content_type(kind, filename):
    """Content type for a stored file, from its name, with the kind's default."""
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or DEFAULT_TYPES[kind]
