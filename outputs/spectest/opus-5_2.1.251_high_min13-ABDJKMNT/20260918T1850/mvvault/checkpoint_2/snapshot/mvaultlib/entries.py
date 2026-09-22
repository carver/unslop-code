"""Applying a source observation to the stored entries of a catalog."""

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
    """
    for category in CATEGORIES:
        entries = {entry["id"]: entry for entry in catalog[category]}
        for source_entry in observed[category]:
            if source_entry["id"] not in entries:
                entries[source_entry["id"]] = _new_entry(source_entry)
            _update(entries[source_entry["id"]], source_entry, timestamp)

        present = {source_entry["id"] for source_entry in observed[category]}
        for entry_id, entry in entries.items():
            if entry_id not in present:
                record(entry["removed"], timestamp, True)

        catalog[category] = sort_entries(entries.values())


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
