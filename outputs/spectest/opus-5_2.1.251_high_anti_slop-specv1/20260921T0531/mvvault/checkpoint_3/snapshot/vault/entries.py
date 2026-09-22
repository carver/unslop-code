"""Catalog entries: static source facts plus six tracked-field histories."""

from . import history

STATIC_FIELDS = ("id", "published", "width", "height")
TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
REMOVED_FIELD = "removed"
ANNOTATIONS_FIELD = "annotations"


def create(source_entry, clock):
    """Build an entry with an initial history point for every tracked field."""
    entry = {field: source_entry[field] for field in STATIC_FIELDS}
    entry.update({field: {} for field in TRACKED_FIELDS})
    entry[REMOVED_FIELD] = {}
    entry[ANNOTATIONS_FIELD] = []
    observe(entry, source_entry, clock)
    return entry


def observe(entry, source_entry, clock):
    """Record changed tracked values and note that the entry is still offered.

    Static fields keep the values captured at first observation. Returns
    whether the observation changed anything, counting a return from removal.
    """
    changed = [history.record(entry[field], source_entry[field], clock) for field in TRACKED_FIELDS]
    returned = history.record(entry[REMOVED_FIELD], False, clock)
    return any(changed) or returned


def mark_removed(entry, clock):
    """Record that the source no longer offers this entry.

    Returns whether this is the sync that lost it, rather than a later sync
    that found it still gone.
    """
    return history.record(entry[REMOVED_FIELD], True, clock)
