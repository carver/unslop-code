"""Tracked-field histories.

A history is a JSON object mapping sync timestamp text to the value observed at
that sync. Because the keys share a fixed-width format, their lexicographic
order is also their chronological order, so the newest key is ``max(history)``.
"""


def latest_key(history):
    """Newest timestamp key in ``history``, or ``None`` when it is empty."""
    return max(history) if history else None


def current_value(history):
    """Value recorded at the newest timestamp key."""
    return history[max(history)]


def record(history, value, clock):
    """Append ``value`` unless it already is the current value.

    ``None`` is an ordinary value here, so a transition between ``None`` and a
    number counts as a change.
    """
    newest = latest_key(history)
    if newest is not None and current_value(history) == value:
        return
    history[clock.stamp_after(newest)] = value
