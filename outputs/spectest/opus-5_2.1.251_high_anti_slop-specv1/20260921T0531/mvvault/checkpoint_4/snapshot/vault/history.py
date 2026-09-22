"""Tracked-field histories.

A history is a JSON object mapping sync timestamp text to the value observed at
that sync. Because the keys share a fixed-width format, their lexicographic
order is also their chronological order, so the newest key is ``max(history)``.
"""


def latest_key(history):
    """Newest timestamp key in ``history``, or ``None`` when it is empty."""
    return max(history) if history else None


def latest_value(history, ordering=str):
    """Value recorded at the newest key, or ``None`` when there is none.

    ``ordering`` is the key function the version's history keys sort by: the
    epoch-second keys of a version 1 catalog order as numbers, the timestamp
    text of later versions as plain strings.
    """
    return history[max(history, key=ordering)] if history else None


def record(history, value, clock):
    """Append ``value`` unless it already is the current value.

    Returns whether a point was appended. ``None`` is an ordinary value here,
    so a transition between ``None`` and a number counts as a change.
    """
    newest = latest_key(history)
    if newest is not None and history[newest] == value:
        return False
    history[clock.stamp_after(newest)] = value
    return True
