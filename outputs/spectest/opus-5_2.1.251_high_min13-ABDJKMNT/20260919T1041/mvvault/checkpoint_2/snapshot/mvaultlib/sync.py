"""Applying a source snapshot to a vault catalog."""

from . import catalog as catalog_module
from . import source as source_module
from .history import SOURCE_TRACKED_FIELDS, latest_key, record
from .schema import CATEGORIES, STATIC_FIELD_TYPES
from .timestamps import format_datetime, next_timestamp, parse_datetime


def sync(name, now):
    """Sync the vault called `name` and return the timestamp that was written.

    A legacy catalog is upgraded in memory first, so the sync always writes a
    native catalog back. The catalog is read and the source validated before
    anything is written, so a failing sync leaves the vault untouched.
    """
    catalog, _ = catalog_module.load(name)
    snapshot = source_module.fetch(catalog["source"])
    stamp = format_datetime(next_timestamp(now, _latest_recorded(catalog)))

    for category in CATEGORIES:
        _apply(catalog[category], snapshot[category], stamp)

    catalog_module.write(name, catalog)
    return stamp


def _latest_recorded(catalog):
    """The newest timestamp already present anywhere in the catalog."""
    newest = latest_key(entry for category in CATEGORIES for entry in catalog[category])
    return parse_datetime(newest) if newest else None


def _apply(entries, source_entries, stamp):
    """Record one observation of `source_entries` into a category's entries."""
    stored = {entry["id"]: entry for entry in entries}

    for source_entry in source_entries:
        existing = stored.get(source_entry["id"])
        if existing is None:
            new_entry = _new_entry(source_entry, stamp)
            stored[new_entry["id"]] = new_entry
            entries.append(new_entry)
        else:
            _observe(existing, source_entry, stamp)

    present = {source_entry["id"] for source_entry in source_entries}
    for entry in entries:
        if entry["id"] not in present:
            record(entry["removed"], stamp, True)


def _new_entry(source_entry, stamp):
    """A first observation: static fields plus six one-key histories."""
    entry = {field: source_entry[field] for field in STATIC_FIELD_TYPES}
    entry.update({field: {stamp: source_entry[field]} for field in SOURCE_TRACKED_FIELDS})
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    return entry


def _observe(entry, source_entry, stamp):
    """A later observation: append only the tracked values that changed."""
    for field in SOURCE_TRACKED_FIELDS:
        record(entry[field], stamp, source_entry[field])
    record(entry["removed"], stamp, False)
