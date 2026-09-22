"""Tracked-field histories: objects mapping timestamp text to the value then."""

TRACKED_FIELDS = ("title", "description", "views", "likes", "preview", "removed")

# The five tracked fields whose values come from the source; `removed` is local.
SOURCE_TRACKED_FIELDS = TRACKED_FIELDS[:-1]


def current_value(history):
    """The value at the chronologically latest key.

    Timestamp text is fixed-width, so the latest key is the greatest string.
    """
    return history[max(history)]


def record(history, value, timestamp):
    """Append `value` at `timestamp` unless it already is the current value."""
    if current_value(history) != value:
        history[timestamp] = value


def latest_key(entry):
    """The newest timestamp recorded anywhere in `entry`, or empty text."""
    keys = [key for field in TRACKED_FIELDS for key in entry.get(field, {})]
    return max(keys, default="")
