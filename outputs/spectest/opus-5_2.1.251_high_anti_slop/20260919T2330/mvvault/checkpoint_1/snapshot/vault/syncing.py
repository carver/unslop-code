"""Merging fetched source entries into a vault catalog."""

from datetime import timedelta

from .catalog import CATEGORIES, HISTORY_FIELDS, STATIC_FIELDS, TRACKED_FIELDS, sort_entries
from .history import append_value, current_value, format_timestamp, parse_timestamp


def sync_timestamp(catalog, now):
    """Pick the sync time, kept strictly newer than every timestamp already recorded."""
    recorded = [
        parse_timestamp(key)
        for category in CATEGORIES
        for entry in catalog[category]
        for field in HISTORY_FIELDS
        for key in entry[field]
    ]
    newest = max(recorded, default=None)
    if newest is not None and now <= newest:
        return newest + timedelta(seconds=1)
    return now


def apply_source(catalog, source_entries, moment):
    """Record new, changed, removed and restored entries at ``moment``."""
    for category in CATEGORIES:
        known = {entry["id"]: entry for entry in catalog[category]}
        for fetched in source_entries[category]:
            entry = known.get(fetched["id"])
            if entry is None:
                catalog[category].append(_new_entry(fetched, moment))
            else:
                _update_entry(entry, fetched, moment)
        present = {fetched["id"] for fetched in source_entries[category]}
        for entry in catalog[category]:
            if entry["id"] not in present and not current_value(entry["removed"]):
                append_value(entry["removed"], True, moment)
        catalog[category] = sort_entries(catalog[category])


def _new_entry(fetched, moment):
    """Build a first-observation entry with an initial history for every tracked field."""
    entry = {field: fetched[field] for field in STATIC_FIELDS}
    key = format_timestamp(moment)
    for field in TRACKED_FIELDS:
        entry[field] = {key: fetched[field]}
    entry["removed"] = {key: False}
    return entry


def _update_entry(entry, fetched, moment):
    """Append history for tracked values that changed, and restore a removed entry."""
    for field in TRACKED_FIELDS:
        if current_value(entry[field]) != fetched[field]:
            append_value(entry[field], fetched[field], moment)
    if current_value(entry["removed"]):
        append_value(entry["removed"], False, moment)
