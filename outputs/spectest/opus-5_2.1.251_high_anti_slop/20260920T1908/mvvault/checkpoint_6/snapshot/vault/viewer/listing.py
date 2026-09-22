"""What the viewer shows about the entries of one category.

A listing repeats the catalog's own order and states, per entry, the two
things the stored files and history decide: whether its media is on disk, and
whether the source has dropped it.
"""

from dataclasses import dataclass
from pathlib import Path

from ..views import CatalogView
from .assets import media_names


@dataclass(frozen=True)
class EntryRow:
    """One entry as the viewer lists it."""

    entry_id: str
    title: str
    downloaded: bool
    removed: bool


def entry_rows(vault_dir: Path, view: CatalogView, entries: list) -> list[EntryRow]:
    """Describe one category's entries, in catalog order."""
    downloaded = media_names(vault_dir)
    return [
        EntryRow(
            entry["id"],
            view.current_value(entry["title"], ""),
            any(entry["id"] in name for name in downloaded),
            view.is_removed(entry),
        )
        for entry in entries
    ]
