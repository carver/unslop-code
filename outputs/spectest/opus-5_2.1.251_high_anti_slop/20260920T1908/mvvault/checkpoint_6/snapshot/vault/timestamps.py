"""Datetime text handling.

Every datetime written by mvault uses the same locale-independent shape,
``YYYY-MM-DDTHH:MM:SS``, so that stored text sorts chronologically.
"""

from datetime import datetime, timezone

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def format_timestamp(moment: datetime) -> str:
    """Render a datetime as vault text, dropping any sub-second or zone detail."""
    return moment.strftime(DATETIME_FORMAT)


def format_epoch(seconds: str) -> str:
    """Render UNIX epoch seconds, the version 1 history key format, as UTC vault text."""
    return format_timestamp(datetime.fromtimestamp(int(seconds), timezone.utc))


def parse_timestamp(text: str) -> datetime:
    """Read back text produced by :func:`format_timestamp`."""
    return datetime.strptime(text, DATETIME_FORMAT)


def normalize_published(text: str) -> str:
    """Convert a source publication value to vault text.

    Accepts ISO 8601 datetimes, with or without a zone suffix, and date-only
    values, which take a ``00:00:00`` time component. Raises ``ValueError``
    for anything else.
    """
    cleaned = text.strip().removesuffix("Z")
    return format_timestamp(datetime.fromisoformat(cleaned).replace(tzinfo=None))
