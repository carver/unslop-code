"""The media files a vault stores for its entries.

Both the download phase and the viewer ask the same question of a vault's
``media/`` directory — is this entry's media already here — so they ask it in
one place.
"""

from pathlib import Path

MEDIA_DIRECTORY = "media"
PREVIEW_DIRECTORY = "previews"
PARTIAL_SUFFIX = ".part"


def stored_names(vault):
    """Names of the finished media files of the vault directory ``vault``.

    The partial file of an interrupted download is left out, so a stale one
    never passes for stored media.
    """
    directory = Path(vault) / MEDIA_DIRECTORY
    return [path.name for path in directory.glob("*") if not path.name.endswith(PARTIAL_SUFFIX)]


def is_stored(identifier, names):
    """Whether one of ``names`` is the media file of the entry ``identifier``."""
    return any(identifier in name for name in names)
