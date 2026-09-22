"""Merging a source snapshot into the stored catalog entries."""

from datetime import datetime

from .changes import ADDED, REAPPEARED, REMOVED, UPDATED, Change, ChangeSet, change_set
from .history import current_value, record
from .schema import CATEGORIES, REMOVED_FIELD, STATIC_FIELDS, TRACKED_FIELDS


def merge_catalog(catalog: dict, snapshot: dict, moment: datetime) -> ChangeSet:
    """Fold a whole source snapshot into a catalog and report what changed."""
    return change_set(
        [
            (category, merge_category(catalog[category], snapshot[category], moment))
            for category in CATEGORIES
        ]
    )


def merge_category(entries: list, source_entries: list, moment: datetime) -> list[Change]:
    """Fold a source snapshot of one category into its stored entries.

    New ids are added, known ids gain history for whatever changed, and ids
    the source no longer lists are marked removed rather than deleted. Each
    entry the merge touched comes back as one change.
    """
    stored_by_id = {entry["id"]: entry for entry in entries}
    changes = []
    for source_entry in source_entries:
        stored = stored_by_id.get(source_entry["id"])
        if stored is None:
            entries.append(_new_entry(source_entry, moment))
            changes.append(_change(ADDED, entries[-1]))
        elif appended := _update_entry(stored, source_entry, moment):
            changes.append(_change(UPDATED, stored, appended))
    published_ids = {source_entry["id"] for source_entry in source_entries}
    for entry in entries:
        if entry["id"] not in published_ids and record(entry[REMOVED_FIELD], True, moment):
            changes.append(_change(REMOVED, entry))
    return changes


def _change(group: str, entry: dict, fields: tuple[str, ...] = ()) -> Change:
    """Describe what the merge did to one entry, under its current title."""
    return Change(group, entry["id"], current_value(entry["title"]), fields)


def _new_entry(source_entry: dict, moment: datetime) -> dict:
    """Build a first observation: static fields plus six histories at ``moment``."""
    entry = {field: source_entry[field] for field in STATIC_FIELDS}
    for field, value in _observed_values(source_entry).items():
        entry[field] = {}
        record(entry[field], value, moment)
    return entry


def _update_entry(entry: dict, source_entry: dict, moment: datetime) -> tuple[str, ...]:
    """Append history for tracked values that changed since the last sync.

    Recording ``removed`` as ``False`` also restores an entry that had
    disappeared from the source and has now come back, which reads as the
    entry reappearing rather than as a field the source edited. Returns the
    names of the fields that gained a value.
    """
    appended = [
        field
        for field, value in _observed_values(source_entry).items()
        if record(entry[field], value, moment)
    ]
    return tuple(REAPPEARED if field == REMOVED_FIELD else field for field in appended)


def _observed_values(source_entry: dict) -> dict:
    """Tracked values implied by a source entry, including the local removed flag."""
    values = {field: source_entry[field] for field in TRACKED_FIELDS}
    values[REMOVED_FIELD] = False
    return values
