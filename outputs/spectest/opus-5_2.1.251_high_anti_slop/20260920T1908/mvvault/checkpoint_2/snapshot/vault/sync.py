"""Merging a source snapshot into the stored catalog entries."""

from datetime import datetime

from .history import record
from .schema import STATIC_FIELDS, TRACKED_FIELDS


def merge_category(entries: list, source_entries: list, moment: datetime) -> None:
    """Fold a source snapshot of one category into its stored entries.

    New ids are added, known ids gain history for whatever changed, and ids
    the source no longer lists are marked removed rather than deleted.
    """
    stored_by_id = {entry["id"]: entry for entry in entries}
    for source_entry in source_entries:
        stored = stored_by_id.get(source_entry["id"])
        if stored is None:
            entries.append(_new_entry(source_entry, moment))
        else:
            _update_entry(stored, source_entry, moment)
    published_ids = {source_entry["id"] for source_entry in source_entries}
    for entry in entries:
        if entry["id"] not in published_ids:
            record(entry["removed"], True, moment)


def _new_entry(source_entry: dict, moment: datetime) -> dict:
    """Build a first observation: static fields plus six histories at ``moment``."""
    entry = {field: source_entry[field] for field in STATIC_FIELDS}
    for field, value in _observed_values(source_entry).items():
        entry[field] = {}
        record(entry[field], value, moment)
    return entry


def _update_entry(entry: dict, source_entry: dict, moment: datetime) -> None:
    """Append history for tracked values that changed since the last sync.

    Recording ``removed`` as ``False`` also restores an entry that had
    disappeared from the source and has now come back.
    """
    for field, value in _observed_values(source_entry).items():
        record(entry[field], value, moment)


def _observed_values(source_entry: dict) -> dict:
    """Tracked values implied by a source entry, including the local removed flag."""
    values = {field: source_entry[field] for field in TRACKED_FIELDS}
    values["removed"] = False
    return values
