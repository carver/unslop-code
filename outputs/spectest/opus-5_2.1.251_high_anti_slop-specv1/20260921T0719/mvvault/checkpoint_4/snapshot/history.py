"""Tracked-field history objects.

A history maps canonical timestamp text to the value the field held from that
moment on.  The current value is the one stored under the newest key; because
mvault timestamps are fixed width, the newest key is also the largest string.
"""

from typing import Any, Optional

from timestamps import next_second

History = dict[str, Any]


def latest_key(history: History) -> Optional[str]:
    """Return the newest timestamp in ``history``, or ``None`` when empty."""
    return max(history, default=None)


def latest_value(history: History) -> Any:
    """Return the value a history holds now, or ``None`` when it is empty."""
    newest = latest_key(history)
    return None if newest is None else history[newest]


def start(timestamp: str, value: Any) -> History:
    """Create a history whose first observation is ``value`` at ``timestamp``."""
    return {timestamp: value}


def record(history: History, timestamp: str, value: Any) -> bool:
    """Append ``value`` at ``timestamp`` unless it repeats the current value.

    Returns whether the value was a change worth recording.  ``None`` is an
    ordinary value here, so moving between ``None`` and a number counts as a
    change.  A timestamp that is not strictly newer than the last one recorded
    is advanced past it so no observation is overwritten.
    """
    newest = latest_key(history)
    if newest is not None:
        if history[newest] == value:
            return False
        if timestamp <= newest:
            timestamp = next_second(newest)
    history[timestamp] = value
    return True
