"""The metadata phase of `sync`: applying a source snapshot to a catalog."""

from collections import Counter

from . import catalog as catalog_module
from . import source as source_module
from .history import SOURCE_TRACKED_FIELDS, latest_key, record
from .schema import CATEGORIES, STATIC_FIELD_TYPES
from .timestamps import format_datetime, next_timestamp, parse_datetime

#: The three change kinds reported by the post-sync summary, in reporting order.
CHANGE_KINDS = ("added", "removed", "updated")


def metadata_phase(name, now):
    """Sync the vault called `name`; return its catalog, stamp and change counts.

    A legacy catalog is upgraded in memory first, so the phase always writes a
    native catalog back. The catalog is read and the source validated before
    anything is written, so a failing sync leaves the vault untouched.
    """
    catalog, _ = catalog_module.load(name)
    snapshot = source_module.fetch(catalog["source"])
    stamp = format_datetime(next_timestamp(now, _latest_recorded(catalog)))

    counts = Counter()
    for category in CATEGORIES:
        counts += _apply(catalog[category], snapshot[category], stamp)

    catalog_module.write(name, catalog)
    return catalog, stamp, counts


def _latest_recorded(catalog):
    """The newest timestamp already present anywhere in the catalog."""
    newest = latest_key(entry for category in CATEGORIES for entry in catalog[category])
    return parse_datetime(newest) if newest else None


def _apply(entries, source_entries, stamp):
    """Record one observation of `source_entries`; return its change counts.

    Every entry contributes to at most one count: a new entry is an addition, an
    entry that has just gone missing is a removal, and any other entry whose
    history grew - a reappearance included - is an update.
    """
    stored = {entry["id"]: entry for entry in entries}
    counts = Counter()

    for source_entry in source_entries:
        existing = stored.get(source_entry["id"])
        if existing is None:
            new_entry = _new_entry(source_entry, stamp)
            stored[new_entry["id"]] = new_entry
            entries.append(new_entry)
            counts["added"] += 1
        elif _observe(existing, source_entry, stamp):
            counts["updated"] += 1

    present = {source_entry["id"] for source_entry in source_entries}
    for entry in entries:
        if entry["id"] not in present and record(entry["removed"], stamp, True):
            counts["removed"] += 1
    return counts


def _new_entry(source_entry, stamp):
    """A first observation: static fields plus six one-key histories."""
    entry = {field: source_entry[field] for field in STATIC_FIELD_TYPES}
    entry.update({field: {stamp: source_entry[field]} for field in SOURCE_TRACKED_FIELDS})
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    return entry


def _observe(entry, source_entry, stamp):
    """A later observation: append the tracked values that changed.

    Every field is recorded before the answer is formed, so that one early
    change does not stop the remaining fields from being observed.
    """
    observed = {field: source_entry[field] for field in SOURCE_TRACKED_FIELDS}
    observed["removed"] = False
    return any([record(entry[field], stamp, value) for field, value in observed.items()])
