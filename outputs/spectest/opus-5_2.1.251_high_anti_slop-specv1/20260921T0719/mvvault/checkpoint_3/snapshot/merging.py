"""Folding freshly fetched source entries into a stored catalog.

Merging counts what it does so ``sync`` can report the changes it recorded:
entries seen for the first time, entries that dropped out of the source and
entries whose tracked fields took a new value.
"""

from dataclasses import dataclass
from typing import Any

import catalogs
import history
from source import SourceData
from timestamps import normalize_published


@dataclass
class SyncSummary:
    """How many entries a merge added, removed and updated."""

    added: int = 0
    removed: int = 0
    updated: int = 0

    def __str__(self) -> str:
        return f"{self.added} added, {self.removed} removed, {self.updated} updated"


def merge(catalog: catalogs.Catalog, data: SourceData, timestamp: str) -> SyncSummary:
    """Record the source state of every category in ``catalog``."""
    summary = SyncSummary()
    for category in catalogs.CATEGORIES:
        catalog[category] = _merge_category(
            catalog[category], data[category], timestamp, summary
        )
    return summary


def _merge_category(
    entries: list[catalogs.Entry],
    items: list[dict[str, Any]],
    timestamp: str,
    summary: SyncSummary,
) -> list[catalogs.Entry]:
    """Fold the source entries of one category into the stored ones."""
    stored = {entry["id"]: entry for entry in entries}
    for item in items:
        entry = stored.get(item["id"])
        if entry is None:
            entries.append(_new_entry(item, timestamp))
            summary.added += 1
        elif _observe(entry, item, timestamp):
            summary.updated += 1
    listed = {item["id"] for item in items}
    for entry in entries:
        if entry["id"] not in listed and history.record(entry["removed"], timestamp, True):
            summary.removed += 1
    return catalogs.sort_entries(entries)


def _new_entry(item: dict[str, Any], timestamp: str) -> catalogs.Entry:
    """Build the stored entry for an identifier seen for the first time."""
    entry = {field: item[field] for field in catalogs.STATIC_FIELDS}
    entry["published"] = normalize_published(item["published"])
    entry.update(
        {
            field: history.start(timestamp, item[field])
            for field in catalogs.SOURCE_TRACKED_FIELDS
        }
    )
    entry["removed"] = history.start(timestamp, False)
    entry["annotations"] = []
    return entry


def _observe(entry: catalogs.Entry, item: dict[str, Any], timestamp: str) -> bool:
    """Extend the histories of a stored entry with its current source values.

    Fields still holding their previous value gain no record, and an entry that
    had been marked removed is restored by the same rule.  Returns whether any
    field changed.
    """
    changed = [
        history.record(entry[field], timestamp, item[field])
        for field in catalogs.SOURCE_TRACKED_FIELDS
    ]
    changed.append(history.record(entry["removed"], timestamp, False))
    return any(changed)
