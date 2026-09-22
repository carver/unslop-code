"""Chart data for an entry's tracked counts, normalized across catalog versions.

A detail page charts `views` and `likes`. Their history keys differ by version --
version 1 stores UNIX-epoch text, later versions ISO 8601 -- so ordering uses the
version's own key comparison while every point is reported with an ISO 8601
timestamp. Values are passed through untouched, `null` likes included.
"""

import json
from dataclasses import dataclass

#: The tracked fields a detail page charts, in the order it shows them.
CHARTED_FIELDS = ("views", "likes")

#: Recorded values a field needs before there is a line worth drawing.
MIN_CHART_POINTS = 2


@dataclass(frozen=True)
class Point:
    """One observation: when it was recorded, and what was recorded."""

    timestamp: str
    value: object


def chart_series(entry, form):
    """Each charted field's points, oldest first, keyed by ISO 8601 timestamps."""
    return {field: _points(entry.get(field, {}), form) for field in CHARTED_FIELDS}


def is_chartable(points):
    """Whether a field has enough recorded values to draw a line through.

    A single-point history has no line, and nor has one whose every other
    observation is `null`. The points are published either way.
    """
    return sum(point.value is not None for point in points) >= MIN_CHART_POINTS


def chart_payload(series):
    """The series as the machine-readable JSON document a page embeds."""
    return json.dumps(
        {
            field: [{"timestamp": point.timestamp, "value": point.value} for point in points]
            for field, points in series.items()
        }
    )


def _points(history, form):
    """One history as points, ordered by the comparison its version calls for."""
    return tuple(
        Point(form.timestamp(key), history[key]) for key in sorted(history, key=form.key)
    )
