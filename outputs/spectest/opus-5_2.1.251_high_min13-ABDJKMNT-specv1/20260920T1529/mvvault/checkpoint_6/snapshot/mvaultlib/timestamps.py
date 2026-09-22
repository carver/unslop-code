"""Datetime text handling: one locale-independent format, no timezone suffix."""

from datetime import datetime, timedelta, timezone

FORMAT = "%Y-%m-%dT%H:%M:%S"


def format_datetime(moment):
    """Render a datetime as `YYYY-MM-DDTHH:MM:SS`."""
    return moment.strftime(FORMAT)


def next_second(text):
    """The timestamp text one second after `text`."""
    return format_datetime(datetime.strptime(text, FORMAT) + timedelta(seconds=1))


def now():
    """The current wall-clock second, as timestamp text."""
    return format_datetime(datetime.now().replace(microsecond=0))


def normalize_published(text):
    """Normalize a published value to the canonical datetime text.

    Date-only values gain a `00:00:00` time component and any timezone suffix
    or sub-second precision is dropped, keeping the wall-clock time as written.
    Text that is not ISO 8601 is kept verbatim: the source schema only promises
    that `published` is a string.
    """
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return text
    return format_datetime(moment.replace(tzinfo=None))


def from_epoch(text):
    """The canonical text for a UNIX-epoch-seconds key, read in UTC."""
    return format_datetime(datetime.fromtimestamp(int(text), tz=timezone.utc))


def checked_datetime(text):
    """`text` unchanged, once confirmed to be ISO 8601 datetime text."""
    datetime.fromisoformat(text)
    return text
