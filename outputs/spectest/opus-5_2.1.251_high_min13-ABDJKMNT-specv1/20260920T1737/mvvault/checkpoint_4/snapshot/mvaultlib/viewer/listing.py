"""The rows a category page shows, derived from a version-aware catalog view.

The viewer reads vaults of every supported version, so the state of a row --
its current title, whether its media is stored, whether it has been removed --
is resolved through the view's own conventions rather than the v3 shape.
"""

from dataclasses import dataclass

from mvaultlib.downloads import MEDIA_DIR, has_media, stored_media_names


@dataclass(frozen=True)
class ListedEntry:
    """One entry of a category listing, in the state the page renders."""

    entry_id: str
    title: str
    downloaded: bool
    removed: bool


def listed_entries(view, group, vault_path):
    """The rows of one category, in the order the catalog stores them."""
    stored = stored_media_names(vault_path / MEDIA_DIR)
    return [_listed_entry(view, entry, stored) for entry in group.entries]


def _listed_entry(view, entry, stored):
    """Resolve one stored entry into the state the listing shows."""
    entry_id = entry["id"]
    return ListedEntry(
        entry_id=entry_id,
        title=view.current_value(entry["title"]),
        downloaded=has_media(entry_id, stored),
        removed=view.tracks_removal and view.current_value(entry["removed"]) is True,
    )
