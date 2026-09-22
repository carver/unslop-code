"""The state an entry detail page renders, resolved from a stored entry.

Like the category listing, a detail page reads its vault through a
`CatalogView`, so the current title and description come from whichever key
format that version uses and the source-platform link is derived per version.
"""

from dataclasses import dataclass

from mvaultlib.downloads import MEDIA_DIR, PREVIEW_DIR, matching_asset, stored_asset_names
from mvaultlib.viewer.charts import chart_series


@dataclass(frozen=True)
class EntryDetail:
    """One entry as its detail page shows it: metadata, assets and charts."""

    entry_id: str
    title: str
    description: str
    published: str
    width: int
    height: int
    #: The entry's address on the source platform.
    source_link: str
    #: The saved media file name matching the entry, or None when none is stored.
    media_file: str
    #: True when a saved preview image matches the entry.
    has_preview: bool
    #: The `views` and `likes` `Series` charted for this entry.
    series: list
    #: The entry's stored annotations, in creation order.
    annotations: list


def entry_detail(view, entry, vault_path):
    """Resolve one stored entry into the state its detail page renders."""
    entry_id = entry["id"]
    return EntryDetail(
        entry_id=entry_id,
        title=view.current_value(entry["title"]),
        description=view.current_value(entry["description"]),
        published=entry["published"],
        width=entry["width"],
        height=entry["height"],
        source_link=view.entry_link(entry_id),
        media_file=_stored_name(vault_path / MEDIA_DIR, entry_id),
        has_preview=_stored_name(vault_path / PREVIEW_DIR, entry_id) is not None,
        series=chart_series(view, entry),
        annotations=entry.get("annotations", []),
    )


def _stored_name(directory, entry_id):
    """The saved file name in `directory` matching `entry_id`, or None."""
    return matching_asset(entry_id, stored_asset_names(directory))
