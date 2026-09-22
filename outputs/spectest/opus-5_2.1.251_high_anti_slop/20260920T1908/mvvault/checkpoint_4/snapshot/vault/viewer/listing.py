"""What the viewer shows about the entries of one category.

A listing repeats the catalog's own order and states, per entry, the two
things the stored files and history decide: whether its media is on disk, and
whether the source has dropped it.
"""

from dataclasses import dataclass
from pathlib import Path

from ..download import MEDIA_DIR
from ..schema import REMOVED_FIELD
from ..views import CatalogView


@dataclass(frozen=True)
class EntryRow:
    """One entry as the viewer lists it."""

    entry_id: str
    title: str
    downloaded: bool
    removed: bool


def entry_rows(vault_dir: Path, view: CatalogView, entries: list) -> list[EntryRow]:
    """Describe one category's entries, in catalog order."""
    media_names = _media_names(vault_dir)
    return [
        EntryRow(
            entry["id"],
            view.ordered_values(entry["title"])[-1],
            any(entry["id"] in name for name in media_names),
            _is_removed(entry, view),
        )
        for entry in entries
    ]


def _media_names(vault_dir: Path) -> list[str]:
    """The media file names of a vault; an entry owns the ones naming its id."""
    media_dir = vault_dir / MEDIA_DIR
    if not media_dir.is_dir():
        return []
    return [path.name for path in media_dir.iterdir() if path.is_file()]


def _is_removed(entry: dict, view: CatalogView) -> bool:
    """Whether the source has dropped an entry, which only version 3 records."""
    if not view.removals_tracked:
        return False
    values = view.ordered_values(entry.get(REMOVED_FIELD, {}))
    return values[-1:] == [True]
