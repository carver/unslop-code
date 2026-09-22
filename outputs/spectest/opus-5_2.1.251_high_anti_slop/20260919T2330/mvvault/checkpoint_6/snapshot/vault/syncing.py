"""Merging fetched source entries into a vault catalog."""

from datetime import timedelta

from .catalog import (
    CATEGORIES,
    HISTORY_FIELDS,
    REMOVED_FIELD,
    STATIC_FIELDS,
    TRACKED_FIELDS,
    sort_entries,
)
from .changes import ADDED, REAPPEARED, REMOVED, UPDATED, EntryChange
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
    """Record new, changed, removed and restored entries at ``moment``.

    Returns the :class:`~vault.changes.EntryChange` of every entry the merge
    touched, in catalog order within each category.
    """
    changes = []
    for category in CATEGORIES:
        changes.extend(_apply_category(catalog, category, source_entries[category], moment))
    return tuple(changes)


def _apply_category(catalog, category, fetched_entries, moment):
    """Merge one category's fetched entries and return what changed in it."""
    known = {entry["id"]: entry for entry in catalog[category]}
    changes = []
    for fetched in fetched_entries:
        entry = known.get(fetched["id"])
        if entry is None:
            entry = _new_entry(fetched, moment)
            catalog[category].append(entry)
            changes.append(EntryChange(category, ADDED, entry))
        else:
            changes.extend(_update_entry(entry, fetched, category, moment))
    present = {fetched["id"] for fetched in fetched_entries}
    for entry in catalog[category]:
        if entry["id"] not in present and not current_value(entry[REMOVED_FIELD]):
            append_value(entry[REMOVED_FIELD], True, moment)
            changes.append(EntryChange(category, REMOVED, entry))
    catalog[category] = sort_entries(catalog[category])
    return changes


def _new_entry(fetched, moment):
    """Build a first-observation entry with an initial history for every tracked field."""
    entry = {field: fetched[field] for field in STATIC_FIELDS}
    key = format_timestamp(moment)
    for field in TRACKED_FIELDS:
        entry[field] = {key: fetched[field]}
    entry[REMOVED_FIELD] = {key: False}
    return entry


def _update_entry(entry, fetched, category, moment):
    """Append history for the tracked values that changed, reporting the entry once.

    A restored entry counts as an update: its ``removed`` flag goes back to false
    and the entry is reported as having reappeared.
    """
    changed = [field for field in TRACKED_FIELDS if current_value(entry[field]) != fetched[field]]
    for field in changed:
        append_value(entry[field], fetched[field], moment)
    if current_value(entry[REMOVED_FIELD]):
        append_value(entry[REMOVED_FIELD], False, moment)
        changed.append(REAPPEARED)
    return [EntryChange(category, UPDATED, entry, tuple(changed))] if changed else []
