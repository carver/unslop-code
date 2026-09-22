"""Stored entries: static fields, tracked-field histories and entry ordering."""

from mvaultlib.errors import MvaultError
from mvaultlib.timestamps import normalize_published, parse_timestamp

#: The three entry categories of a catalog, in their documented order.
CATEGORIES = ("episodes", "streams", "clips")

STATIC_FIELD_TYPES = {"id": str, "published": str, "width": int, "height": int}

#: Tracked fields whose values come from the source document.
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")

#: Every tracked field, including the locally maintained `removed` flag.
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)


def latest_key(history):
    """The newest datetime key, read in chronological order."""
    return max(history, key=parse_timestamp)


def current_value(history):
    """The value at the newest datetime key."""
    return history[latest_key(history)]


def create_entry(source_entry, timestamp):
    """Build a first-observation entry: statics plus one history entry each."""
    entry = {
        "id": source_entry["id"],
        "published": normalize_published(source_entry["published"]),
        "width": source_entry["width"],
        "height": source_entry["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        entry[field] = {timestamp: source_entry[field]}
    entry["removed"] = {timestamp: False}
    entry["annotations"] = []
    return entry


def record_observation(entry, source_entry, timestamp):
    """Record the source values of an entry that is present in this sync."""
    for field in SOURCE_TRACKED_FIELDS:
        record_change(entry[field], source_entry[field], timestamp)
    record_change(entry["removed"], False, timestamp)


def record_absence(entry, timestamp):
    """Record that an entry is no longer offered by the source."""
    record_change(entry["removed"], True, timestamp)


def record_change(history, value, timestamp):
    """Append `value` unless it already is the current value of the history."""
    if current_value(history) != value:
        history[timestamp] = value


def sort_entries(entries):
    """Newest `published` first, ties broken by lexicographically smaller `id`."""
    by_id = sorted(entries, key=lambda entry: entry["id"])
    return sorted(by_id, key=lambda entry: entry["published"], reverse=True)


def validate_entry(entry, label):
    """Raise `MvaultError` unless the stored entry matches the entry schema."""
    if not isinstance(entry, dict):
        raise MvaultError(f"{label} entry is not an object")
    for field, expected in STATIC_FIELD_TYPES.items():
        if not isinstance(entry.get(field), expected) or isinstance(entry.get(field), bool):
            raise MvaultError(f"{label} entry has a missing or mistyped '{field}'")
    for field in TRACKED_FIELDS:
        _validate_history(entry.get(field), f"{label} entry '{entry['id']}' field '{field}'")


def _validate_history(history, label):
    if not isinstance(history, dict) or not history:
        raise MvaultError(f"{label} is not a non-empty history object")
    for key in history:
        try:
            parse_timestamp(key)
        except (TypeError, ValueError) as error:
            raise MvaultError(f"{label} has an invalid datetime key '{key}'") from error
