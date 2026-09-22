"""What the entry detail page shows about one catalog entry.

Every version is read in the shape it stores, then normalized here: a current
value is the one at the latest key in that version's key order, a chart point
carries an ISO 8601 timestamp whatever the history keys look like, and the
source-platform link is derived from the vault's own source URL, which version 1
gets from its ``source_id``. The page rendering never has to know the version.
"""

from typing import NamedTuple
from urllib.parse import quote

from . import assets, versions, viewer

#: Tracked fields the detail page charts, in the order it draws them.
CHART_FIELDS = ("views", "likes")
#: A history shorter than this describes no movement, so it gets no chart.
MIN_CHART_POINTS = 2


class EntryDetail(NamedTuple):
    """One entry as its page shows it; the URL fields are empty when nothing is stored.

    ``charts`` maps a charted field to its points, oldest first, each point a
    ``timestamp``/``value`` pair.
    """

    id: str
    title: str
    description: str
    published: str
    width: int
    height: int
    source_link: str
    media_url: str
    preview_url: str
    charts: dict


def find_entry(entries, entry_id):
    """The entry ``entry_id`` names within one category's list, or ``None``.

    The search never leaves the list it is given, so the same id under another
    category does not answer for this one, and an entry the source dropped is
    still found.
    """
    return next((entry for entry in entries if entry["id"] == entry_id), None)


def build(name, loaded, entry):
    """Collect everything the detail page of ``entry`` renders."""
    entry_id = entry["id"]
    media_file = viewer.downloaded_media(name, entry_id)
    preview = assets.locate(name, viewer.PREVIEW_ROUTE, entry_id)
    return EntryDetail(
        id=entry_id,
        title=versions.latest_value(entry["title"], loaded.key_order),
        description=versions.latest_value(entry["description"], loaded.key_order),
        published=entry["published"],
        width=entry["width"],
        height=entry["height"],
        source_link=source_link(loaded.source, entry_id),
        media_url=viewer.media_path(name, media_file) if media_file else "",
        preview_url=viewer.preview_path(name, entry_id) if preview else "",
        charts=chart_data(entry, loaded),
    )


def source_link(source, entry_id):
    """URL of the entry on the platform the vault syncs from."""
    return f"{source.rstrip('/')}/entry/{quote(entry_id)}"


def chart_data(entry, loaded):
    """Chart points per charted field, leaving out the histories that plot nothing."""
    charted = ((field, points(entry[field], loaded)) for field in CHART_FIELDS)
    return {field: series for field, series in charted if len(series) >= MIN_CHART_POINTS}


def points(history, loaded):
    """One history as chronological points, oldest first, timestamped in ISO 8601.

    Values are passed through as they were observed: a ``null`` stays a ``null``.
    """
    return [
        {"timestamp": loaded.key_timestamp(key), "value": history[key]}
        for key in sorted(history, key=loaded.key_order)
    ]
