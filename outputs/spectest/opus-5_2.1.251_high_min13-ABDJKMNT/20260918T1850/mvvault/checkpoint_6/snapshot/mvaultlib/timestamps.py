"""Datetime text handling: one format, no timezones, no locale dependence.

Parsing relies on `datetime.fromisoformat`, which since Python 3.11 accepts the
full ISO 8601 grammar the source may use: date-only text, a `T` or space
separator, fractional seconds, and `Z` or numeric UTC offsets.
"""

from datetime import datetime, timedelta, timezone


def format_datetime(value):
    """Render a datetime as `YYYY-MM-DDTHH:MM:SS`, dropping offset and microseconds."""
    return value.replace(microsecond=0, tzinfo=None).isoformat()


def parse_datetime(text):
    """Parse text produced by `format_datetime`."""
    return datetime.fromisoformat(text)


def epoch_to_iso(key):
    """A UNIX-epoch string as canonical datetime text in UTC.

    Version 1 catalogs key their histories by epoch seconds; every later reader
    works in the canonical text, so this is where the two meet.
    """
    return format_datetime(datetime.fromtimestamp(int(key), timezone.utc))


def normalize_published(text):
    """Normalize a source `published` value to the canonical datetime text.

    Date-only text picks up a `00:00:00` time component. A timezone suffix is
    dropped rather than converted: the rule is about the shape of the text, not
    about moving the instant into another zone.

    Raises ValueError if the text is not a date or a datetime.
    """
    return format_datetime(datetime.fromisoformat(text.strip()))


def allocate_sync_timestamp(newest_recorded):
    """Pick the timestamp every history entry of one sync run is written at.

    It reflects the current execution time, but advances to a strictly later
    second when that would collide with -- or fall behind -- the newest
    timestamp already stored in the vault. History keys are therefore never
    reused, and successive syncs always read as strictly increasing.
    """
    stamp = format_datetime(datetime.now())
    if newest_recorded is not None and stamp <= newest_recorded:
        stamp = format_datetime(parse_datetime(newest_recorded) + timedelta(seconds=1))
    return stamp
