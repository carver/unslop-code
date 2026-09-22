"""Applying a source observation to the stored entries of a catalog."""

from collections import Counter

from .catalog import CATEGORIES, sort_entries
from .history import SOURCE_TRACKED_FIELDS, TRACKED_FIELDS, is_integer, is_text, record

#: Entry fields copied verbatim from the source, without history, and their types.
STATIC_VALIDATORS = {
    "id": is_text,
    "published": is_text,
    "width": is_integer,
    "height": is_integer,
}

STATIC_FIELDS = tuple(STATIC_VALIDATORS)


def apply_observation(catalog, observed, timestamp):
    """Fold one source observation into `catalog`, recording at `timestamp`.

    `observed` maps each category to its validated source entries. Entries the
    source no longer lists are kept and marked removed rather than deleted.

    Returns how many entries this observation added, removed and updated.
    """
    changes = Counter()
    for category in CATEGORIES:
        entries = {entry["id"]: entry for entry in catalog[category]}
        created = set()
        for source_entry in observed[category]:
            if source_entry["id"] not in entries:
                entries[source_entry["id"]] = _new_entry(source_entry)
                created.add(source_entry["id"])
            _update(entries[source_entry["id"]], source_entry, timestamp)

        present = {source_entry["id"] for source_entry in observed[category]}
        for entry_id, entry in entries.items():
            if entry_id not in present:
                record(entry["removed"], timestamp, True)
            group = _classify(entry, timestamp, entry_id in created)
            if group:
                changes[group] += 1

        catalog[category] = sort_entries(entries.values())
    return changes


def _classify(entry, timestamp, is_new):
    """Which summary group this run put the entry in, if any.

    The groups follow the same precedence a digest uses, so an entry counts
    once: gone first, then brand new, then changed in some other way.
    """
    if entry["removed"].get(timestamp) is True:
        return "removed"
    if is_new:
        return "added"
    if any(timestamp in entry[field] for field in TRACKED_FIELDS):
        return "updated"
    return None


def _new_entry(source_entry):
    """A first-observation entry: static fields copied, histories still empty."""
    return {
        **{field: source_entry[field] for field in STATIC_FIELDS},
        **{field: {} for field in TRACKED_FIELDS},
    }


def _update(entry, source_entry, timestamp):
    """Refresh static fields and append history for every changed tracked value."""
    for field in STATIC_FIELDS:
        entry[field] = source_entry[field]
    for field in SOURCE_TRACKED_FIELDS:
        record(entry[field], timestamp, source_entry[field])
    record(entry["removed"], timestamp, False)
