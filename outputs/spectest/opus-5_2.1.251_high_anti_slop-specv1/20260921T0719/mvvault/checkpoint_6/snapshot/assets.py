"""The media and preview files a vault holds, as the viewer serves them.

A vault names its downloads after the entry they belong to, but the extension
follows whatever the source returned, so a file is found by the identifier its
name contains rather than by a name the viewer can compute.  Lookups never
leave the directory they search, so a request cannot reach outside the vault.
"""

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import downloads

#: Content type a stored file is served with when its name does not name one.
MEDIA_TYPE = "video/mp4"
IMAGE_TYPE = "image/jpeg"


@dataclass(frozen=True)
class Asset:
    """One stored file and the content type it is served under."""

    path: Path
    content_type: str


@dataclass(frozen=True)
class EntryFiles:
    """What a vault holds for one entry, as its detail page links to it."""

    #: Name of the stored media file, or ``None`` when none was downloaded.
    media: Optional[str]
    #: Whether a preview image of the entry is stored.
    preview: bool


def media(vault: Path, filename: str) -> Optional[Asset]:
    """The stored media file called ``filename``, if the vault holds it."""
    path = _inside(vault / downloads.MEDIA_DIRECTORY, filename)
    return None if path is None else Asset(path, _content_type(path, MEDIA_TYPE))


def preview(vault: Path, identifier: str) -> Optional[Asset]:
    """The stored preview image whose filename contains ``identifier``."""
    path = _named_after(vault / downloads.PREVIEW_DIRECTORY, identifier)
    return None if path is None else Asset(path, _content_type(path, IMAGE_TYPE))


def entry_files(vault: Path, identifier: str) -> EntryFiles:
    """The files a vault holds for the entry called ``identifier``."""
    held = _named_after(vault / downloads.MEDIA_DIRECTORY, identifier)
    return EntryFiles(
        media=None if held is None else held.name,
        preview=preview(vault, identifier) is not None,
    )


def _inside(directory: Path, filename: str) -> Optional[Path]:
    """The file ``filename`` names in ``directory``, unless it points elsewhere.

    A name carrying its own separators, or one climbing out of the directory,
    lands somewhere the viewer serves nothing from and is refused here.
    """
    path = directory / filename
    return path if path.parent == directory and path.is_file() else None


def _named_after(directory: Path, identifier: str) -> Optional[Path]:
    """The first stored file of ``directory`` whose name holds ``identifier``.

    Leftovers of an interrupted download carry the identifier too but hold no
    complete file, so they are passed over the way a sync passes over them.
    """
    matches = sorted(
        path
        for path in directory.glob("*")
        if identifier in path.name
        and not path.name.endswith(downloads.PARTIAL_SUFFIX)
        and path.is_file()
    )
    return matches[0] if matches else None


def _content_type(path: Path, fallback: str) -> str:
    """The content type the name of a stored file stands for."""
    return mimetypes.guess_type(path.name)[0] or fallback
