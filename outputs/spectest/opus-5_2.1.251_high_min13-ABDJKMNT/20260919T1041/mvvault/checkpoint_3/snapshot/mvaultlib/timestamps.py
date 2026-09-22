"""Datetime text handling: one locale-independent second-precision format."""

from datetime import datetime, timedelta

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def format_datetime(moment):
    """Render a datetime as `YYYY-MM-DDTHH:MM:SS`, without timezone suffix."""
    return moment.strftime(DATETIME_FORMAT)


def current_stamp():
    """The current wall-clock second in the stored datetime format."""
    return format_datetime(datetime.now())


def parse_datetime(text):
    """Read back a timestamp written by :func:`format_datetime`."""
    return datetime.strptime(text, DATETIME_FORMAT)


def normalize_datetime(text):
    """Normalize ISO 8601 source text to the stored format.

    Date-only text gains a `00:00:00` time component; any timezone suffix and
    sub-second precision is dropped. Raises `ValueError` for unparseable text.
    """
    parsed = datetime.fromisoformat(text)
    return format_datetime(parsed.replace(tzinfo=None, microsecond=0))


def next_timestamp(now, latest_recorded):
    """The stamp to write for a sync started at `now`.

    Truncated to the second and advanced to a strictly later second than
    anything already recorded, so appended history keys always increase.
    """
    stamp = now.replace(microsecond=0)
    if latest_recorded is not None and stamp <= latest_recorded:
        return latest_recorded + timedelta(seconds=1)
    return stamp
