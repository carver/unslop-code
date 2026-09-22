"""Timestamp text used throughout a vault.

Every datetime written to a catalog is locale-independent
``YYYY-MM-DDTHH:MM:SS`` text with no timezone suffix, which keeps the keys of a
tracked-field history sortable as plain strings.
"""

from datetime import datetime, timedelta

ONE_SECOND = timedelta(seconds=1)


def format_timestamp(moment):
    """Render ``moment`` as second-resolution text without a timezone suffix."""
    return moment.replace(tzinfo=None, microsecond=0).isoformat(sep="T", timespec="seconds")


def parse_timestamp(text):
    """Read timestamp text back into a naive :class:`~datetime.datetime`."""
    return datetime.fromisoformat(text)


def normalize_published(text):
    """Normalize an ISO 8601 date or datetime to stored timestamp text.

    Date-only values gain a ``00:00:00`` time component and any timezone offset
    is dropped. Raises :class:`ValueError` for text that is not ISO 8601.
    """
    return format_timestamp(datetime.fromisoformat(text))


class SyncClock:
    """Hands out the sync timestamps used for new history entries.

    Stamps start at the second the sync began and never repeat or move
    backwards: when a history already holds a key at or after the clock's
    current second, the clock advances to a strictly later second first.
    """

    def __init__(self, started_at):
        self._current = started_at.replace(microsecond=0)

    def stamp_after(self, latest_key):
        """Return a stamp strictly later than ``latest_key`` (``None`` if new)."""
        if latest_key is not None:
            latest = parse_timestamp(latest_key)
            if latest >= self._current:
                self._current = latest + ONE_SECOND
        return format_timestamp(self._current)
