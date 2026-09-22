"""The ``views`` and ``likes`` charts of an entry.

Both fields are tracked history, so both plot their values against the moments
they were observed at. The view hands the points over already normalized, so a
version 1 vault charts the same way a version 3 one does. A field observed only
once states a moment rather than a course and is left out; the rest of the page
does not depend on it.

Every chart's points are also embedded in the page as JSON, so the numbers
behind a line stay readable by anything that parses the page instead of looking
at it. They are embedded exactly as they were recorded: a ``likes`` observation
the source did not report stays ``null`` rather than becoming a zero.
"""

import json
from dataclasses import dataclass
from html import escape

from ..views import CatalogView

CHART_FIELDS = ("views", "likes")
MIN_POINTS = 2
PAYLOAD_ID = "chart-data"
MISSING_VALUE = "—"

SERIES_COLORS = {"views": "#2a78d6", "likes": "#eb6834"}

PLOT_WIDTH = 640
PLOT_HEIGHT = 200
PLOT_LEFT = 70
PLOT_RIGHT = 624
PLOT_TOP = 30
PLOT_BASE = 156
TIME_LABEL_Y = 178
MARKER_RADIUS = 4
HIT_RADIUS = 12

STYLE = """
.chart { margin: 1.75rem 0; }
.chart figcaption { font-weight: 600; }
.plot { width: 100%; height: auto; margin: .25rem 0; }
.plot .grid { stroke: #e4e4e4; stroke-width: 1; }
.plot .line { fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.plot .marker { stroke: #ffffff; stroke-width: 2; }
.plot .hit { fill: transparent; }
.plot .point:hover .marker { r: 6; }
.plot text { fill: #5b5b5b; font-size: 11px; }
.plot .latest { fill: #1b1b1b; font-weight: 600; }
.points { border-collapse: collapse; font-size: .8rem; margin-top: .5rem; }
.points th, .points td { border-bottom: 1px solid #e4e4e4; padding: .2rem 1.2rem .2rem 0; text-align: left; }
"""


@dataclass(frozen=True)
class Series:
    """One tracked field's history, as the points a chart is drawn from."""

    field: str
    points: tuple[tuple[str, int | None], ...]


def chart_series(view: CatalogView, entry: dict) -> tuple[Series, ...]:
    """The chartable histories of one entry, in field order.

    A history that holds a single observation has no course to draw and is
    left out, so an entry seen once charts nothing.
    """
    histories = ((field, view.ordered_points(entry.get(field, {}))) for field in CHART_FIELDS)
    return tuple(
        Series(field, tuple(points))
        for field, points in histories
        if len(points) >= MIN_POINTS
    )


def chart_section(series: tuple[Series, ...]) -> str:
    """The charts of one entry, followed by the points they were drawn from."""
    figures = "\n".join(_figure(one) for one in series)
    return f'<section class="charts">\n{figures}\n{_payload(series)}\n</section>'


def _payload(series: tuple[Series, ...]) -> str:
    """Embed the points as JSON, with ``<`` escaped so no value can close the element."""
    data = {
        one.field: [{"timestamp": moment, "value": value} for moment, value in one.points]
        for one in series
    }
    encoded = json.dumps(data).replace("<", "\\u003c")
    return f'<script type="application/json" id="{PAYLOAD_ID}">{encoded}</script>'


def _figure(series: Series) -> str:
    """One field's chart, with the table of values it was drawn from below it."""
    return (
        '<figure class="chart">'
        f"<figcaption>{series.field.capitalize()} over time</figcaption>"
        f"{_plot(series)}{_table(series)}"
        "</figure>"
    )


def _plot(series: Series) -> str:
    """Draw one series as a line over its observations."""
    low, high = _bounds(series.points)
    spots = _spots(series.points, low, high)
    return (
        f'<svg class="plot" viewBox="0 0 {PLOT_WIDTH} {PLOT_HEIGHT}" role="img" '
        f'aria-label="{series.field} across {len(series.points)} observations">'
        f"{_axes(series, _marks(spots, low, high))}"
        f"{_lines(spots, SERIES_COLORS[series.field])}"
        f"{_markers(series, spots)}"
        f"{_latest_value(series, spots)}"
        "</svg>"
    )


def _bounds(points: tuple) -> tuple[int, int]:
    """The lowest and highest value a series reaches, ignoring moments without one."""
    values = [value for _, value in points if value is not None]
    return (min(values), max(values)) if values else (0, 0)


def _spots(points: tuple, low: int, high: int) -> list[tuple[int, float, float]]:
    """Where each observed value sits in the plot, with its place in the series.

    Observations are spaced evenly, so the x axis carries their order and the
    timestamps under the plot say which stretch of time that order covers.
    Moments without a value take no place on the line.
    """
    step = (PLOT_RIGHT - PLOT_LEFT) / (len(points) - 1)
    return [
        (index, PLOT_LEFT + index * step, _height(value, low, high))
        for index, (_, value) in enumerate(points)
        if value is not None
    ]


def _height(value: int, low: int, high: int) -> float:
    """How high above the baseline a value is drawn.

    A series that never moved has no span to spread over and runs straight
    through the middle of the plot.
    """
    if high == low:
        return (PLOT_TOP + PLOT_BASE) / 2
    return PLOT_BASE - (value - low) / (high - low) * (PLOT_BASE - PLOT_TOP)


def _marks(spots: list, low: int, high: int) -> dict[float, int]:
    """The values a reader measures a line against: the highest and lowest it reaches.

    A series that never moved reaches one value, so it is measured against the
    single height its line runs along rather than two carrying the same number.
    One the source never reported a number for has nothing to measure at all.
    """
    return {_height(value, low, high): value for value in (high, low)} if spots else {}


def _axes(series: Series, marks: dict[float, int]) -> str:
    """The gridlines a value is read against, and the span of time below them."""
    grid = "".join(
        f'<line class="grid" x1="{PLOT_LEFT}" y1="{y:.1f}" x2="{PLOT_RIGHT}" y2="{y:.1f}"></line>'
        f'<text x="{PLOT_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">{value:,}</text>'
        for y, value in marks.items()
    )
    return (
        f"{grid}"
        f'<text x="{PLOT_LEFT}" y="{TIME_LABEL_Y}">{escape(series.points[0][0])}</text>'
        f'<text x="{PLOT_RIGHT}" y="{TIME_LABEL_Y}" text-anchor="end">'
        f"{escape(series.points[-1][0])}</text>"
    )


def _lines(spots: list, color: str) -> str:
    """Connect the observed values, breaking the line where one is missing."""
    return "".join(
        f'<polyline class="line" stroke="{color}" points="{_coordinates(run)}"></polyline>'
        for run in _runs(spots)
        if len(run) >= MIN_POINTS
    )


def _coordinates(run: list) -> str:
    """One stretch of the line, as the ``x,y`` pairs an SVG polyline reads."""
    return " ".join(f"{x:.1f},{y:.1f}" for _, x, y in run)


def _runs(spots: list) -> list[list]:
    """Split the plotted spots into stretches of consecutive observations."""
    runs = [[]]
    for spot in spots:
        if runs[-1] and spot[0] != runs[-1][-1][0] + 1:
            runs.append([])
        runs[-1].append(spot)
    return runs


def _markers(series: Series, spots: list) -> str:
    """A dot per observed value, each naming its moment and value on hover.

    The dot a reader aims at is wider than the dot they see, because a point
    on a line is too small to hit reliably.
    """
    color = SERIES_COLORS[series.field]
    return "".join(
        f'<g class="point"><title>{escape(series.points[index][0])}: '
        f"{series.points[index][1]:,}</title>"
        f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="{HIT_RADIUS}"></circle>'
        f'<circle class="marker" cx="{x:.1f}" cy="{y:.1f}" r="{MARKER_RADIUS}" '
        f'fill="{color}"></circle></g>'
        for index, x, y in spots
    )


def _latest_value(series: Series, spots: list) -> str:
    """Label the newest value, which is the number a reader comes to the chart for."""
    if not spots:
        return ""
    index, x, y = spots[-1]
    return (
        f'<text class="latest" x="{x:.1f}" y="{y - 12:.1f}" text-anchor="end">'
        f"{series.points[index][1]:,}</text>"
    )


def _table(series: Series) -> str:
    """The values behind the line, for reading rather than looking."""
    rows = "".join(
        f"<tr><td>{escape(moment)}</td><td>{_cell(value)}</td></tr>"
        for moment, value in series.points
    )
    return (
        f"<details><summary>{len(series.points)} recorded values</summary>"
        f'<table class="points">'
        f"<thead><tr><th>Recorded</th><th>{series.field.capitalize()}</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></details>"
    )


def _cell(value: int | None) -> str:
    """An observation the source did not report reads as missing, not as a zero."""
    return MISSING_VALUE if value is None else f"{value:,}"
