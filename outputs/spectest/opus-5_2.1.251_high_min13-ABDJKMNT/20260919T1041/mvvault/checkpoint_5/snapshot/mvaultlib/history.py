"""Tracked-field history objects: datetime key -> value at that time."""

TRACKED_FIELDS = ("title", "description", "views", "likes", "preview", "removed")

#: Tracked fields whose values come straight from a source entry.
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")


def current_value(history):
    """The value at the latest datetime key.

    Keys share a fixed-width format, so the largest key is also the newest.
    """
    return history[max(history)]


def record(history, stamp, value):
    """Append `value` at `stamp` unless it already is the current value.

    Returns whether the history actually grew, which is what the post-sync
    summary counts as a change to the entry.
    """
    if current_value(history) == value:
        return False
    history[stamp] = value
    return True


def latest_key(entries):
    """The newest datetime key across the tracked fields of `entries`."""
    keys = (key for entry in entries for field in TRACKED_FIELDS for key in entry[field])
    return max(keys, default=None)
