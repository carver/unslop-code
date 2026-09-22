"""The ``views`` and ``likes`` histories of an entry, as data and as charts.

Both fields are read through the vault's own version-aware view, so the points
of a legacy history carry the same ISO 8601 timestamps as a native one's. They
reach the page twice: once as a JSON block, which is the machine-readable form
of the chart data and doubles as the page's data view, and once as a
server-rendered line chart per field that has a line to draw.

The two fields are charted apart rather than on shared axes: a view count and
a like count are measures of different scale, and one pair of axes cannot tell
the truth about both.
"""

import json
from collections import namedtuple
from html import escape

from .. import history

#: The tracked count fields a detail page charts.
CHART_FIELDS = ("views", "likes")
#: Id of the JSON block the chart data is embedded in.
DATA_ID = "chart-data"
#: The fewest points a line can be drawn through.
MINIMUM_POINTS = 2

#: One field's history: its name and its ``(timestamp, value)`` points.
Series = namedtuple("Series", "field points")

WIDTH = 640
HEIGHT = 180
MARGIN_LEFT = 56
MARGIN_RIGHT = 16
MARGIN_TOP = 16
MARGIN_BOTTOM = 32
PLOT_WIDTH = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
PLOT_HEIGHT = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
BASELINE = MARGIN_TOP + PLOT_HEIGHT
MARKER_RADIUS = 4
#: Distance from the plot to a label, and the rise that sits one on its line.
LABEL_GAP = 8
TICK_RISE = 4


def series(view, entry):
    """The charted histories of ``entry``, each with its points oldest first."""
    return [
        Series(field, history.points(entry[field], view.ordering, view.to_timestamp))
        for field in CHART_FIELDS
    ]


def markup(charts):
    """The chart data block, followed by a chart per field with a line to draw."""
    drawable = ((found.field, _known(found.points)) for found in charts)
    return "\n".join([
        _data(charts),
        *(_chart(field, points) for field, points in drawable if len(points) >= MINIMUM_POINTS),
    ])


def _data(charts):
    """Every charted field as JSON, with its points and values as stored.

    Timestamps come from the catalog, so the one character that could end the
    block early is written as the escape JSON has for it.
    """
    payload = {
        found.field: [{"timestamp": stamp, "value": value} for stamp, value in found.points]
        for found in charts
    }
    text = json.dumps(payload).replace("<", "\\u003c")
    return f'<script type="application/json" id="{DATA_ID}">{text}</script>'


def _known(points):
    """The points a line can pass through: a ``null`` value has no height."""
    return [(stamp, value) for stamp, value in points if value is not None]


def _chart(field, points):
    """One field's line chart: a titled figure around an inline SVG.

    A single series needs no legend, so the figure's heading names the field
    and the marks carry nothing but the field's own colour.
    """
    values = [value for _, value in points]
    low, high = min(values), max(values)
    places = [
        (MARGIN_LEFT + index * PLOT_WIDTH / (len(points) - 1), _height(value, low, high))
        for index, value in enumerate(values)
    ]
    return (
        f'<figure class="chart chart-{field}">'
        f"<h2>{field}</h2>"
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{field} over time">'
        f"{_frame(low, high, points[0][0], points[-1][0])}"
        f'<polyline class="line" points="{_line(places)}"/>'
        f"{_markers(places, points)}"
        "</svg></figure>"
    )


def _height(value, low, high):
    """Vertical place of ``value``; a history that never moved sits mid-plot."""
    if high == low:
        return MARGIN_TOP + PLOT_HEIGHT / 2
    return MARGIN_TOP + PLOT_HEIGHT * (high - value) / (high - low)


def _line(places):
    """The ``points`` attribute of the polyline through ``places``."""
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in places)


def _markers(places, points):
    """A marker per point, each naming its timestamp and value on hover."""
    return "".join(
        f'<circle class="point" cx="{x:.1f}" cy="{y:.1f}" r="{MARKER_RADIUS}">'
        f"<title>{escape(stamp)}: {value}</title></circle>"
        for (x, y), (stamp, value) in zip(places, points)
    )


def _frame(low, high, first, last):
    """The recessive parts: a hairline per value bound, and the labels on them."""
    return (
        f'<line class="grid" x1="{MARGIN_LEFT}" y1="{MARGIN_TOP}"'
        f' x2="{WIDTH - MARGIN_RIGHT}" y2="{MARGIN_TOP}"/>'
        f'<line class="grid" x1="{MARGIN_LEFT}" y1="{BASELINE}"'
        f' x2="{WIDTH - MARGIN_RIGHT}" y2="{BASELINE}"/>'
        f'<text class="tick" x="{MARGIN_LEFT - LABEL_GAP}" y="{MARGIN_TOP + TICK_RISE}"'
        f' text-anchor="end">{high}</text>'
        f'<text class="tick" x="{MARGIN_LEFT - LABEL_GAP}" y="{BASELINE + TICK_RISE}"'
        f' text-anchor="end">{low}</text>'
        f'<text class="tick" x="{MARGIN_LEFT}" y="{HEIGHT - LABEL_GAP}">{escape(first)}</text>'
        f'<text class="tick" x="{WIDTH - MARGIN_RIGHT}" y="{HEIGHT - LABEL_GAP}"'
        f' text-anchor="end">{escape(last)}</text>'
    )
