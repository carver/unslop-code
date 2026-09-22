"""Timestamp text and tracked-field history handling.

A tracked field is stored as an object mapping ISO 8601 datetime strings to the
value observed at that time; the value at the latest key is the current one.
"""

from datetime import datetime, timedelta

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def format_timestamp(moment):
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SS`` with no timezone suffix."""
    return moment.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(text):
    """Read an ISO 8601 datetime or date-only string as a naive datetime."""
    return datetime.fromisoformat(text).replace(tzinfo=None)


def normalize_published(text):
    """Normalize a source ``published`` value; date-only text gets a ``00:00:00`` time."""
    return format_timestamp(parse_timestamp(text))


def latest_key(history):
    """Return the newest timestamp key of a history object."""
    return max(history, key=parse_timestamp)


def current_value(history):
    """Return the value recorded at the newest timestamp key."""
    return history[latest_key(history)]


def append_value(history, value, moment):
    """Record ``value`` at ``moment``, advancing past any existing non-newer second."""
    if history:
        newest = parse_timestamp(latest_key(history))
        if moment <= newest:
            moment = newest + timedelta(seconds=1)
    history[format_timestamp(moment)] = value
