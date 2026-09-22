"""Tracked-field history objects.

A history maps vault datetime text to the value observed at that moment. The
current value of a field is the value stored under its latest key.
"""

from datetime import datetime, timedelta

from .timestamps import format_timestamp, parse_timestamp


def current_value(history: dict):
    """Return the value at the latest timestamp of a non-empty history."""
    return history[max(history)]


def record(history: dict, value, moment: datetime) -> bool:
    """Append ``value`` at ``moment`` unless it already is the current value.

    Returns whether the value was appended, which is what makes an observation
    a change worth reporting. ``None`` is an ordinary value here: a transition
    between ``None`` and a number counts as a change, and repeating ``None``
    does not.
    """
    if history and current_value(history) == value:
        return False
    history[_free_timestamp(history, moment)] = value
    return True


def _free_timestamp(history: dict, moment: datetime) -> str:
    """Pick a key for ``moment`` that is strictly later than every existing one."""
    timestamp = format_timestamp(moment)
    if not history:
        return timestamp
    latest = max(history)
    if timestamp > latest:
        return timestamp
    return format_timestamp(parse_timestamp(latest) + timedelta(seconds=1))
