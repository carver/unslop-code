"""What the viewer shows about one entry.

A detail page states an entry's current metadata, where it lives on the source
platform, which of its files the vault has downloaded and the history behind
its charts. Everything is read in the catalog's own version, so a version 1
vault reads the same way a version 3 one does.
"""

from dataclasses import dataclass
from pathlib import Path

from ..views import CatalogView
from .assets import media_name, preview_name
from .charts import Series, chart_series


@dataclass(frozen=True)
class EntryDetail:
    """One entry as its own page states it."""

    entry_id: str
    title: str
    description: str
    published: str
    width: int
    height: int
    source_url: str
    media_file: str | None
    has_preview: bool
    removed: bool
    series: tuple[Series, ...]


def entry_detail(
    vault_dir: Path, view: CatalogView, entries: list, entry_id: str
) -> EntryDetail | None:
    """Describe the entry of ``entries`` carrying ``entry_id``, or ``None`` when there is none.

    Only the entries handed in are searched, so an id that belongs to another
    category of the same vault does not resolve here. An entry the source has
    dropped still has a page; it says so.
    """
    entry = next((candidate for candidate in entries if candidate["id"] == entry_id), None)
    if entry is None:
        return None
    return EntryDetail(
        entry_id,
        view.current_value(entry["title"], ""),
        view.current_value(entry.get("description", {}), ""),
        entry.get("published", ""),
        entry.get("width", 0),
        entry.get("height", 0),
        view.entry_url(entry_id),
        media_name(vault_dir, entry_id),
        preview_name(vault_dir, entry_id) is not None,
        view.is_removed(entry),
        chart_series(view, entry),
    )
