"""The `sync` command: merge source metadata into a vault catalog."""

from datetime import datetime

from mvaultlib.catalog import CATEGORIES, load_catalog, write_catalog
from mvaultlib.entries import (
    TRACKED_FIELDS,
    create_entry,
    record_absence,
    record_observation,
    sort_entries,
)
from mvaultlib.source import fetch_source
from mvaultlib.timestamps import format_timestamp, next_timestamp, parse_timestamp


def sync_vault(name, now=None):
    """Fetch the vault source and record new, changed, removed and restored entries."""
    vault_path, catalog = load_catalog(name)
    source_categories = fetch_source(catalog["source"])
    timestamp = format_timestamp(next_timestamp(now or datetime.now(), _latest_timestamp(catalog)))
    for category in CATEGORIES:
        catalog[category] = _merge_category(catalog[category], source_categories[category], timestamp)
    write_catalog(vault_path, catalog)


def _merge_category(stored_entries, source_entries, timestamp):
    """Apply one category of source entries to the stored entries of that category."""
    entries_by_id = {entry["id"]: entry for entry in stored_entries}
    for source_entry in source_entries:
        stored_entry = entries_by_id.get(source_entry["id"])
        if stored_entry is None:
            entries_by_id[source_entry["id"]] = create_entry(source_entry, timestamp)
        else:
            record_observation(stored_entry, source_entry, timestamp)

    offered_ids = {source_entry["id"] for source_entry in source_entries}
    for entry_id, entry in entries_by_id.items():
        if entry_id not in offered_ids:
            record_absence(entry, timestamp)
    return sort_entries(entries_by_id.values())


def _latest_timestamp(catalog):
    """The newest history key anywhere in the catalog, or None when it is empty."""
    keys = [
        key
        for category in CATEGORIES
        for entry in catalog[category]
        for field in TRACKED_FIELDS
        for key in entry[field]
    ]
    if not keys:
        return None
    return max(parse_timestamp(key) for key in keys)
