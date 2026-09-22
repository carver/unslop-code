"""Syncing a vault against its source: new, changed, removed and restored entries."""

from .catalog import load_catalog, save_catalog, sort_entries
from .history import SOURCE_TRACKED_FIELDS, latest_key, record
from .source import CATEGORIES, fetch_source
from .timestamps import next_second, normalize_published, now


def sync_vault(name):
    """Fetch the vault's source and fold it into the catalog."""
    catalog = load_catalog(name)
    payload = fetch_source(catalog["source"])
    timestamp = sync_timestamp(catalog)

    for category in CATEGORIES:
        merge_category(catalog[category], payload[category], timestamp)
        sort_entries(catalog[category])

    save_catalog(name, catalog)


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
    """Apply one category of source entries to the stored entries in place."""
    stored = {entry["id"]: entry for entry in entries}
    incoming = {entry["id"]: entry for entry in source_entries}

    for entry_id, source_entry in incoming.items():
        if entry_id in stored:
            update_entry(stored[entry_id], source_entry, timestamp)
        else:
            entries.append(new_entry(source_entry, timestamp))

    for entry_id, entry in stored.items():
        if entry_id not in incoming:
            record(entry["removed"], True, timestamp)


def new_entry(source_entry, timestamp):
    """Build a first-observation entry: static values plus initial histories."""
    entry = {
        "id": source_entry["id"],
        "published": normalize_published(source_entry["published"]),
        "width": source_entry["width"],
        "height": source_entry["height"],
        "removed": {timestamp: False},
    }
    entry.update({field: {timestamp: source_entry[field]} for field in SOURCE_TRACKED_FIELDS})
    return entry


def update_entry(entry, source_entry, timestamp):
    """Append history for every tracked field whose value changed.

    Static fields keep their first-observation values; a present entry is also
    restored, which appends `removed: false` only if it was removed before.
    """
    for field in SOURCE_TRACKED_FIELDS:
        record(entry[field], source_entry[field], timestamp)
    record(entry["removed"], False, timestamp)
