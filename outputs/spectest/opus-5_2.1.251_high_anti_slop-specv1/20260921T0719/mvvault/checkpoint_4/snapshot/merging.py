"""Folding freshly fetched source entries into a stored catalog.

A merge keeps a record of every entry it touched so ``sync`` can report the
changes it made: entries seen for the first time, entries that dropped out of
the source and entries whose tracked fields took a new value.
"""

from dataclasses import dataclass, field
from typing import Any

import catalogs
import history
from source import SourceData
from timestamps import normalize_published

#: What a merge can do to one entry, in the order a summary counts them.
ADDED = "added"
REMOVED = "removed"
UPDATED = "updated"
KINDS = (ADDED, REMOVED, UPDATED)


@dataclass(frozen=True)
class EntryChange:
    """One entry a merge touched, and where a reader can go look at it."""

    kind: str
    category: str
    identifier: str
    title: str


@dataclass
class SyncSummary:
    """The entries one merge touched, in the order it visited them."""

    changes: list[EntryChange] = field(default_factory=list)

    def record(self, kind: str, category: str, entry: catalogs.Entry) -> None:
        """Note what happened to one entry, under its current title."""
        self.changes.append(
            EntryChange(kind, category, entry["id"], history.latest_value(entry["title"]))
        )

    def count(self, kind: str) -> int:
        """How many entries a merge treated in one way."""
        return sum(1 for change in self.changes if change.kind == kind)

    def __str__(self) -> str:
        return ", ".join(f"{self.count(kind)} {kind}" for kind in KINDS)


def merge(catalog: catalogs.Catalog, data: SourceData, timestamp: str) -> SyncSummary:
    """Record the source state of every category in ``catalog``."""
    summary = SyncSummary()
    for category in catalogs.CATEGORIES:
        catalog[category] = _merge_category(
            catalog[category], data[category], timestamp, category, summary
        )
    return summary


def _merge_category(
    entries: list[catalogs.Entry],
    items: list[dict[str, Any]],
    timestamp: str,
    category: str,
    summary: SyncSummary,
) -> list[catalogs.Entry]:
    """Fold the source entries of one category into the stored ones."""
    stored = {entry["id"]: entry for entry in entries}
    for item in items:
        entry = stored.get(item["id"])
        if entry is None:
            entry = _new_entry(item, timestamp)
            entries.append(entry)
            summary.record(ADDED, category, entry)
        elif _observe(entry, item, timestamp):
            summary.record(UPDATED, category, entry)
    listed = {item["id"] for item in items}
    for entry in entries:
        if entry["id"] not in listed and history.record(entry["removed"], timestamp, True):
            summary.record(REMOVED, category, entry)
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
