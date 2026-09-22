"""The media and preview files a vault stores for its entries.

The download phase, the viewer's listings and the viewer's static routes all
ask the same questions of a vault's asset directories — which files are
finished, and which of them belongs to this entry — so they ask them here.
"""

from pathlib import Path

MEDIA_DIRECTORY = "media"
PREVIEW_DIRECTORY = "previews"
PARTIAL_SUFFIX = ".part"


def stored_names(vault, kind=MEDIA_DIRECTORY):
    """Names of the finished files the vault directory ``vault`` holds in ``kind``.

    The partial file of an interrupted download is left out, so a stale one
    never passes for stored media, and the names are sorted, so the file
    picked for an entry never depends on directory order.
    """
    directory = Path(vault) / kind
    return sorted(path.name for path in directory.glob("*") if not path.name.endswith(PARTIAL_SUFFIX))


def stored_file(identifier, names):
    """First of ``names`` that is a file of the entry ``identifier``, or ``None``.

    A stored asset is named after the entry it was fetched for, so a name
    holding the id is that entry's file.
    """
    return next((name for name in names if identifier in name), None)
