"""Merging a source snapshot into a vault catalog."""

from . import catalog, entries
from .source import CATEGORIES


def merge(stored, snapshot, clock):
    """Apply one source snapshot to every category of ``stored`` in place."""
    for category in CATEGORIES:
        stored[category] = _merge_category(stored[category], snapshot[category], clock)


def _merge_category(stored_entries, source_entries, clock):
    """Return the category's entries after folding in the source listing.

    Entries are never dropped: ones the source no longer offers gain a
    ``removed: true`` history point instead.
    """
    known = {entry["id"]: entry for entry in stored_entries}
    for source_entry in source_entries:
        identifier = source_entry["id"]
        if identifier in known:
            entries.observe(known[identifier], source_entry, clock)
        else:
            known[identifier] = entries.create(source_entry, clock)
    offered = {source_entry["id"] for source_entry in source_entries}
    for identifier, entry in known.items():
        if identifier not in offered:
            entries.mark_removed(entry, clock)
    return catalog.sort_entries(known.values())
