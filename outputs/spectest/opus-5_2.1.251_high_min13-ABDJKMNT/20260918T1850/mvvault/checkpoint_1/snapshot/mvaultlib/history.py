"""Tracked-field histories: JSON objects mapping a sync timestamp to a value."""

#: Tracked fields whose values come straight from the source entry.
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")

#: Every tracked field, including the locally derived `removed` flag.
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

#: Returned by `current_value` for a history that has no entries yet.
UNSET = object()


def current_value(history):
    """Value at the latest timestamp key, or `UNSET` for an empty history."""
    if not history:
        return UNSET
    return history[max(history)]


def record(history, timestamp, value):
    """Append `value` at `timestamp` unless it is already the current value.

    `None` is an ordinary value here, so a transition in or out of `None`
    counts as a change just like any other.
    """
    if current_value(history) != value:
        history[timestamp] = value


def newest_timestamp(entries):
    """The latest timestamp recorded in any tracked history of `entries`.

    Returns None when nothing has been recorded yet.
    """
    keys = [
        key
        for entry in entries
        for field in TRACKED_FIELDS
        for key in entry[field]
    ]
    return max(keys, default=None)
