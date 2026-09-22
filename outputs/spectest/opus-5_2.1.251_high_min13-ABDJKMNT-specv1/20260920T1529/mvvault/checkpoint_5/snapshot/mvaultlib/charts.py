"""The detail page's `views` and `likes` charts.

Each chart carries the series twice: once as JSON, so anything reading the page
picks the points up exactly as the catalog recorded them, and once as a drawing.
The series is normalized here — timestamps are ISO 8601 whatever the catalog
version stores, and points run oldest first — so nothing downstream has to know
which version an entry came from. The two fields measure different things and
are drawn as two charts rather than two lines on one scale.
"""

import json
from html import escape
from itertools import groupby

CHART_FIELDS = ("views", "likes")

# One fixed hue per field, so a field looks the same on every entry and vault.
SERIES_COLOURS = {"views": "#2a78d6", "likes": "#eb6834"}

# A single recorded point has no change to show, so it is left unplotted.
MIN_POINTS = 2

PLOT_WIDTH = 480
PLOT_HEIGHT = 96
MARKER_RADIUS = 4
# Room at the edges of the viewbox for a marker and its stroke.
PADDING = 8


def chart_series(view, entry):
    """`{field: [(ISO timestamp, value), ...]}` for the fields worth plotting."""
    series = {}
    for field in CHART_FIELDS:
        points = [(view.moment(key), value) for key, value in view.points(entry, field)]
        if len(points) >= MIN_POINTS:
            series[field] = points
    return series


def charts(view, entry):
    """An entry's chart section: the embedded series, then a plot of each."""
    series = chart_series(view, entry)
    if not series:
        return ""
    figures = "\n".join(figure(field, points) for field, points in series.items())
    return f'<section class="charts">\n{embedded(series)}\n{figures}\n</section>'


def embedded(series):
    """The series as JSON: machine-readable, and inert inside an HTML page."""
    payload = {
        field: [{"timestamp": moment, "value": value} for moment, value in points]
        for field, points in series.items()
    }
    # A script element ends at the first `</`, which a catalog value could hold.
    text = json.dumps(payload).replace("<", "\\u003c")
    return f'<script type="application/json" id="chart-data">{text}</script>'


def figure(field, points):
    """One field's series as a chart, its oldest point on the left."""
    return (
        f'<figure class="chart">\n'
        f"<h2>{field}</h2>\n"
        f"{plot(field, points)}"
        f"<figcaption>{len(points)} points, {points[0][0]} to {points[-1][0]}</figcaption>\n"
        f"</figure>"
    )


def plot(field, points):
    """The series drawn as a line with a marker naming each point it passes.

    `likes` is allowed to be `null`: a missing value breaks the line rather
    than being drawn as a zero, so each run of recorded values is its own line.
    """
    runs = placed_runs(points)
    if not runs:
        return ""

    colour = SERIES_COLOURS[field]
    lines = "".join(
        f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in run)}"'
        f' fill="none" stroke="{colour}" stroke-width="2"/>'
        for run in runs
    )
    markers = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{MARKER_RADIUS}" fill="{colour}">'
        f"<title>{escape(moment)}: {value}</title></circle>"
        for run in runs
        for x, y, moment, value in run
    )
    return (
        f'<svg class="plot" viewBox="0 0 {PLOT_WIDTH} {PLOT_HEIGHT}" role="img"'
        f' aria-label="{field} over time">{lines}{markers}</svg>\n'
    )


def placed_runs(points):
    """The recorded points placed in the viewbox, grouped into the unbroken
    runs a single line can be drawn through.

    Every point keeps its place along the x axis whether or not it has a value,
    so a gap in the line sits where the missing reading belongs.
    """
    values = [value for _, value in points if value is not None]
    if not values:
        return []

    lowest, span = min(values), (max(values) - min(values)) or 1
    step = (PLOT_WIDTH - 2 * PADDING) / max(len(points) - 1, 1)
    placed = [
        (PADDING + index * step, moment, value) for index, (moment, value) in enumerate(points)
    ]
    return [
        [(x, level(value, lowest, span), moment, value) for x, moment, value in run]
        for recorded, run in groupby(placed, key=lambda mark: mark[2] is not None)
        if recorded
    ]


def level(value, lowest, span):
    """The y coordinate of `value`, the smallest value sitting at the bottom."""
    return PLOT_HEIGHT - PADDING - (value - lowest) / span * (PLOT_HEIGHT - 2 * PADDING)
