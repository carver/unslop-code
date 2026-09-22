"""Chart data for the entry detail page, normalized across catalog versions.

A history is stored under whatever key format its catalog version uses -- v1
keys are UNIX-epoch strings, v2 and v3 keys are ISO 8601 text -- so a series is
built through the vault's own `CatalogView`: it orders the keys the way that
version compares them and renders each one as ISO 8601 for the payload.
"""

from dataclasses import dataclass

#: The tracked fields the detail page charts, in the order it shows them.
CHART_FIELDS = ("views", "likes")

#: Points needed before a series can be drawn as a line.
MIN_CHART_POINTS = 2


@dataclass(frozen=True)
class Series:
    """One tracked field's history as `(timestamp, value)` points, oldest first.

    Every recorded point is kept: values are neither filtered nor replaced, so a
    `likes` history that records `null` charts that `null`.
    """

    field: str
    points: list


def chart_series(view, entry):
    """The `views` and `likes` series of one entry, in this version's order."""
    return [_series(view, entry[field], field) for field in CHART_FIELDS]


def chart_payload(entry_id, series):
    """The machine-readable chart data the detail page embeds."""
    return {
        "entry": entry_id,
        "charts": {
            one.field: [{"timestamp": stamp, "value": value} for stamp, value in one.points]
            for one in series
        },
    }


def plot_points(points, width, height):
    """Chart points as SVG coordinates, skipping points that carry no value.

    `x` is the point's position in the series and `y` scales its value into
    `height` with the largest value at the top. A series without two values to
    compare yields no coordinates, so no line is drawn for it.
    """
    values = [value for _, value in points if value is not None]
    if len(values) < MIN_CHART_POINTS:
        return []
    low, span = min(values), (max(values) - min(values)) or 1
    step = width / (len(points) - 1)
    return [
        (index * step, height - height * (value - low) / span)
        for index, (_, value) in enumerate(points)
        if value is not None
    ]


def _series(view, history, field):
    """One stored history as ordered points carrying ISO 8601 timestamps."""
    points = [(view.chart_timestamp(key), history[key]) for key in view.ordered_keys(history)]
    return Series(field, points)
