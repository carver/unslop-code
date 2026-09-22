"""Locale-independent datetime text handling.

Every datetime written by mvault uses ``YYYY-MM-DDTHH:MM:SS`` with no timezone
suffix, so timestamps compare chronologically when compared lexicographically.
"""

from datetime import datetime, timedelta, timezone

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def format_timestamp(moment: datetime) -> str:
    """Render a naive datetime as canonical mvault timestamp text."""
    return moment.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(text: str) -> datetime:
    """Read canonical mvault timestamp text back into a naive datetime."""
    return datetime.strptime(text, TIMESTAMP_FORMAT)


def next_second(text: str) -> str:
    """Return the canonical timestamp one second after ``text``."""
    return format_timestamp(parse_timestamp(text) + timedelta(seconds=1))


def normalize_published(text: str) -> str:
    """Normalize a source publication value to canonical timestamp text.

    Date-only values gain a ``00:00:00`` time component and offset-aware values
    are converted to UTC before the offset is dropped.  Text that is not ISO
    8601 at all is kept as published by the source.
    """
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return text
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return format_timestamp(moment)
