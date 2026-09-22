"""Datetime text handling.

Every datetime written by mvault uses `YYYY-MM-DDTHH:MM:SS` with no timezone
suffix, which makes lexicographic text order match chronological order.
"""

from datetime import datetime, timedelta, timezone

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def format_timestamp(moment):
    """Render a datetime as the canonical mvault datetime text."""
    return moment.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(text):
    """Read ISO 8601 datetime text, dropping any timezone suffix it carries."""
    candidate = text.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1]
    return datetime.fromisoformat(candidate).replace(tzinfo=None, microsecond=0)


def epoch_to_timestamp(text):
    """Render a UNIX-epoch string as canonical datetime text, read as UTC."""
    return format_timestamp(datetime.fromtimestamp(int(text), tz=timezone.utc))


def normalize_published(text):
    """Normalize source publication text to the canonical datetime format.

    Date-only values gain a `00:00:00` time component and timezone suffixes are
    dropped without shifting the wall clock. Text that is not ISO 8601 at all is
    kept verbatim, since the spec only describes ISO 8601 input.
    """
    try:
        return format_timestamp(parse_timestamp(text))
    except ValueError:
        return text


def next_timestamp(now, latest_existing):
    """Pick the timestamp for a sync run.

    The run uses the current time, advanced to a strictly later second whenever
    that would reuse -- or predate -- the newest timestamp already recorded in
    the vault, so appended history stays strictly increasing.
    """
    candidate = now.replace(microsecond=0)
    if latest_existing is not None and candidate <= latest_existing:
        candidate = latest_existing + timedelta(seconds=1)
    return candidate
