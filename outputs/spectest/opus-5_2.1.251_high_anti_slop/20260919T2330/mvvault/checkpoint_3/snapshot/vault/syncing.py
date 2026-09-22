"""Merging fetched source entries into a vault catalog."""

from datetime import timedelta
from typing import NamedTuple

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


class SyncSummary(NamedTuple):
    """How many entries a sync added, marked removed and changed a tracked field of."""

    added: int = 0
    removed: int = 0
    updated: int = 0

    def __add__(self, other):
        return SyncSummary(*(mine + theirs for mine, theirs in zip(self, other)))


def apply_source(catalog, source_entries, moment):
    """Record new, changed, removed and restored entries at ``moment``.

    Returns the :class:`SyncSummary` of what the merge changed.
    """
    summary = SyncSummary()
    for category in CATEGORIES:
        summary += _apply_category(catalog, category, source_entries[category], moment)
    return summary


def _apply_category(catalog, category, fetched_entries, moment):
    """Merge one category's fetched entries and return the counts they changed."""
    known = {entry["id"]: entry for entry in catalog[category]}
    added = updated = 0
    for fetched in fetched_entries:
        entry = known.get(fetched["id"])
        if entry is None:
            catalog[category].append(_new_entry(fetched, moment))
            added += 1
        else:
            updated += _update_entry(entry, fetched, moment)
    present = {fetched["id"] for fetched in fetched_entries}
    removed = 0
    for entry in catalog[category]:
        if entry["id"] not in present and not current_value(entry["removed"]):
            append_value(entry["removed"], True, moment)
            removed += 1
    catalog[category] = sort_entries(catalog[category])
    return SyncSummary(added, removed, updated)


def _new_entry(fetched, moment):
    """Build a first-observation entry with an initial history for every tracked field."""
    entry = {field: fetched[field] for field in STATIC_FIELDS}
    key = format_timestamp(moment)
    for field in TRACKED_FIELDS:
        entry[field] = {key: fetched[field]}
    entry["removed"] = {key: False}
    return entry


def _update_entry(entry, fetched, moment):
    """Append history for tracked values that changed; returns 1 when anything did.

    A restored entry counts as an update: its ``removed`` flag goes back to false.
    """
    changed = [field for field in TRACKED_FIELDS if current_value(entry[field]) != fetched[field]]
    for field in changed:
        append_value(entry[field], fetched[field], moment)
    if current_value(entry["removed"]):
        append_value(entry["removed"], False, moment)
        return 1
    return 1 if changed else 0
