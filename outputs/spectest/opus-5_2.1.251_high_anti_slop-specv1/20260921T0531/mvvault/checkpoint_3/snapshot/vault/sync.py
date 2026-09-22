"""Merging a source snapshot into a vault catalog."""

from collections import namedtuple

from . import catalog, entries
from .source import CATEGORIES

Changes = namedtuple("Changes", "added removed updated")


def merge(stored, snapshot, clock):
    """Apply one source snapshot to every category of ``stored`` in place.

    Returns the :class:`Changes` this sync made, counted over all categories.
    """
    counted = []
    for category in CATEGORIES:
        stored[category], changes = _merge_category(stored[category], snapshot[category], clock)
        counted.append(changes)
    return Changes(*(sum(counts) for counts in zip(*counted)))


def _merge_category(stored_entries, source_entries, clock):
    """Return the category's entries after folding in the source listing, and
    what changed in it.

    Entries are never dropped: ones the source no longer offers gain a
    ``removed: true`` history point instead.
    """
    known = {entry["id"]: entry for entry in stored_entries}
    added = updated = removed = 0
    for source_entry in source_entries:
        identifier = source_entry["id"]
        if identifier in known:
            updated += entries.observe(known[identifier], source_entry, clock)
        else:
            known[identifier] = entries.create(source_entry, clock)
            added += 1
    offered = {source_entry["id"] for source_entry in source_entries}
    for identifier, entry in known.items():
        if identifier not in offered:
            removed += entries.mark_removed(entry, clock)
    return catalog.sort_entries(known.values()), Changes(added, removed, updated)
