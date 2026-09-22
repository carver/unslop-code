"""Syncing a vault: the metadata phase, the download phase, and the summary.

A run does the metadata phase (fetch the source, fold it into the catalog,
persist it) and then the download phase (retrieve media and previews); either
phase can be skipped. Metadata is always persisted before downloads start, so
a download failure can never cost the run its recorded history.
"""

from collections import Counter
from dataclasses import dataclass, field

from .catalog import load_catalog, save_catalog, sort_entries
from .download import download_assets
from .history import SOURCE_TRACKED_FIELDS, latest_key, record
from .source import CATEGORIES, fetch_source
from .timestamps import next_second, normalize_published, now

ADDED = "added"
REMOVED = "removed"
UPDATED = "updated"


@dataclass(frozen=True)
class SyncOptions:
    """The `sync` switches: per-category caps, format override, phase skips."""

    limits: dict = field(default_factory=dict)
    media_format: str | None = None
    skip_metadata: bool = False
    skip_download: bool = False


DEFAULTS = SyncOptions()


def sync_vault(name, options=DEFAULTS):
    """Run the metadata phase, the download phase, or whichever is not skipped."""
    catalog, _ = load_catalog(name)

    if not options.skip_metadata:
        changes = update_metadata(name, catalog)
        print(f"{changes[ADDED]} added, {changes[REMOVED]} removed, {changes[UPDATED]} updated")

    if not options.skip_download:
        download_assets(name, catalog, options.limits, options.media_format)


def update_metadata(name, catalog):
    """Fold the source into the catalog and save it; returns the change counts."""
    payload = fetch_source(catalog["source"])
    timestamp = sync_timestamp(catalog)

    changes = Counter()
    for category in CATEGORIES:
        changes += merge_category(catalog[category], payload[category], timestamp)
        sort_entries(catalog[category])

    save_catalog(name, catalog)
    return changes


def sync_timestamp(catalog):
    """The timestamp this sync appends at.

    It is the current second, advanced to a strictly later second whenever the
    catalog already holds a history key that is not older, so that successive
    syncs always append under strictly increasing timestamps.
    """
    entries = (entry for category in CATEGORIES for entry in catalog[category])
    newest = max((latest_key(entry) for entry in entries), default="")
    timestamp = now()
    return next_second(newest) if timestamp <= newest else timestamp


def merge_category(entries, source_entries, timestamp):
    """Apply one category of source entries in place; returns its change counts."""
    stored = {entry["id"]: entry for entry in entries}
    incoming = {entry["id"]: entry for entry in source_entries}
    changes = Counter()

    for entry_id, source_entry in incoming.items():
        if entry_id not in stored:
            entries.append(new_entry(source_entry, timestamp))
            changes[ADDED] += 1
        elif update_entry(stored[entry_id], source_entry, timestamp):
            changes[UPDATED] += 1

    for entry_id, entry in stored.items():
        if entry_id not in incoming and record(entry["removed"], True, timestamp):
            changes[REMOVED] += 1

    return changes


def new_entry(source_entry, timestamp):
    """Build a first-observation entry: static values plus initial histories."""
    entry = {
        "id": source_entry["id"],
        "published": normalize_published(source_entry["published"]),
        "width": source_entry["width"],
        "height": source_entry["height"],
        "removed": {timestamp: False},
        "annotations": [],
    }
    entry.update({name: {timestamp: source_entry[name]} for name in SOURCE_TRACKED_FIELDS})
    return entry


def update_entry(entry, source_entry, timestamp):
    """Append history for every tracked field whose value changed.

    Static fields keep their first-observation values; a present entry is also
    restored, which appends `removed: false` only if it was removed before.
    Returns whether anything was appended.
    """
    appended = [
        record(entry[tracked], source_entry[tracked], timestamp)
        for tracked in SOURCE_TRACKED_FIELDS
    ]
    restored = record(entry["removed"], False, timestamp)
    return restored or any(appended)
