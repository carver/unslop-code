"""Merging a source snapshot into a vault catalog."""

from collections import Counter, namedtuple

from . import catalog, entries, history
from .source import CATEGORIES

ADDED = "Added"
REMOVED = "Removed"
UPDATED = "Updated"

#: What one sync did to one entry, named by the title it now carries.
EntryChange = namedtuple("EntryChange", "category identifier title kind")

#: What one sync did, counted by kind and listed entry by entry.
Changes = namedtuple("Changes", "added removed updated entries")


def merge(stored, snapshot, clock):
    """Apply one source snapshot to every category of ``stored`` in place.

    Returns the :class:`Changes` this sync made, over all categories.
    """
    changed = []
    for category in CATEGORIES:
        stored[category], made = _merge_category(
            stored[category], snapshot[category], clock, category
        )
        changed.extend(made)
    counts = Counter(change.kind for change in changed)
    return Changes(counts[ADDED], counts[REMOVED], counts[UPDATED], changed)


def _merge_category(stored_entries, source_entries, clock, category):
    """Return the category's entries after folding in the source listing, and
    the changes that made.

    Entries are never dropped: ones the source no longer offers gain a
    ``removed: true`` history point instead.
    """
    known = {entry["id"]: entry for entry in stored_entries}
    changed = []
    for source_entry in source_entries:
        identifier = source_entry["id"]
        if identifier not in known:
            known[identifier] = entries.create(source_entry, clock)
            changed.append(_change(category, known[identifier], ADDED))
        elif entries.observe(known[identifier], source_entry, clock):
            changed.append(_change(category, known[identifier], UPDATED))
    offered = {source_entry["id"] for source_entry in source_entries}
    for identifier, entry in known.items():
        if identifier not in offered and entries.mark_removed(entry, clock):
            changed.append(_change(category, entry, REMOVED))
    return catalog.sort_entries(known.values()), changed


def _change(category, entry, kind):
    """Note what became of one entry, under the title it currently holds."""
    return EntryChange(category, entry["id"], history.latest_value(entry["title"]), kind)
