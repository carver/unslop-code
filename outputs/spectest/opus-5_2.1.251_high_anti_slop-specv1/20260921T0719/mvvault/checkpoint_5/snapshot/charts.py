"""The `views` and `likes` charts of an entry detail page.

Each tracked number is drawn on its own, against its own scale, and the points
it is drawn from are embedded beside it as JSON so the page carries the numbers
it plots.  Timestamps are canonical text whatever version the vault stores its
history keys in, and no observation is dropped or replaced on the way here: a
`likes` history that was never reported keeps its nulls.
"""

import json
from dataclasses import dataclass
from typing import Optional

from catalogs import Entry
from views import CatalogView

#: The tracked fields a detail page plots, each on a chart of its own.
CHART_FIELDS = ("views", "likes")

#: Observations a field needs before it is worth a chart.
MINIMUM_POINTS = 2

#: Element the embedded chart points can be read from.
DATA_ID = "chart-data"

#: Drawing area of one chart, and the margin its line keeps inside it.  The
#: margin leaves room above the highest point for the value labelling it.
WIDTH = 480
HEIGHT = 160
PADDING = 24

STYLE = """
section.charts { display: flex; flex-wrap: wrap; gap: 1rem; }
figure.chart { margin: 0; }
figure.chart figcaption { color: #52514e; font-size: 0.85rem; }
svg.chart { background: #fcfcfb; width: 100%; max-width: 30rem; }
svg.chart polyline { fill: none; stroke: #2a78d6; stroke-width: 2; }
svg.chart circle { fill: #2a78d6; }
svg.chart line.baseline { stroke: #d6d5d0; stroke-width: 1; }
svg.chart text { fill: #52514e; font-family: system-ui, sans-serif; font-size: 11px; }
"""


@dataclass(frozen=True)
class Point:
    """One observation of a tracked number, at the moment it was recorded."""

    timestamp: str
    value: Optional[int]


@dataclass(frozen=True)
class Series:
    """Everything one chart is drawn from: a field and its points in order."""

    field: str
    points: list[Point]


def charts(view: CatalogView, entry: Entry) -> str:
    """The chart section of a detail page, or nothing when there is none.

    A field observed only once has no shape to show, so it is left out; an
    entry where that holds for both fields contributes no section at all.
    """
    plotted = [series for field in CHART_FIELDS if (series := _series(view, entry, field))]
    if not plotted:
        return ""
    figures = "".join(_figure(series) for series in plotted)
    return f"<section class='charts'>{_data(plotted)}{figures}</section>"


def _series(view: CatalogView, entry: Entry, field: str) -> Optional[Series]:
    """The points of one field, unless it was observed too few times."""
    points = [Point(timestamp, value) for timestamp, value in view.series(entry, field)]
    return Series(field, points) if len(points) >= MINIMUM_POINTS else None


def _data(plotted: list[Series]) -> str:
    """Embed the plotted points as JSON, keyed by the field they belong to.

    The text is escaped so that a value holding markup stays a value rather
    than ending the script element it sits in.
    """
    payload = {
        series.field: [
            {"timestamp": point.timestamp, "value": point.value} for point in series.points
        ]
        for series in plotted
    }
    embedded = json.dumps(payload).replace("<", "\\u003c")
    return f"<script id='{DATA_ID}' type='application/json'>{embedded}</script>"


def _figure(series: Series) -> str:
    """One chart: the field it plots, named, above the line it plots it as."""
    return (
        f"<figure class='chart' data-field='{series.field}'>"
        f"<figcaption>{series.field}</figcaption>{_svg(series)}</figure>"
    )


def _svg(series: Series) -> str:
    """Draw a field as a line through the observations that hold a number.

    An observation the source never reported interrupts nothing: the line runs
    through the values around it, which keeps the shape of the field readable
    without inventing a number the vault never saw.
    """
    reported = [
        (index, point) for index, point in enumerate(series.points) if point.value is not None
    ]
    if len(reported) < MINIMUM_POINTS:
        return ""
    values = [point.value for _, point in reported]
    low, high = min(values), max(values)
    drawn = [
        (_x(index, len(series.points)), _y(point.value, low, high)) for index, point in reported
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in drawn)
    dots = "".join(
        f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4'>"
        f"<title>{point.timestamp}: {point.value}</title></circle>"
        for (_, point), (x, y) in zip(reported, drawn)
    )
    return (
        f"<svg class='chart' viewBox='0 0 {WIDTH} {HEIGHT}' role='img' "
        f"aria-label='{series.field}, {values[0]} to {values[-1]}'>"
        f"<line class='baseline' x1='{PADDING}' y1='{HEIGHT - PADDING}' "
        f"x2='{WIDTH - PADDING}' y2='{HEIGHT - PADDING}'/>"
        f"<polyline points='{line}'/>{dots}{_labels(drawn, values)}</svg>"
    )


def _labels(drawn: list[tuple[float, float]], values: list[int]) -> str:
    """Name the first and last value drawn, the two a reader looks for."""
    first, last = (drawn[0], values[0]), (drawn[-1], values[-1])
    return "".join(
        f"<text x='{x:.1f}' y='{y - 10:.1f}' text-anchor='{anchor}'>{value}</text>"
        for ((x, y), value), anchor in ((first, "start"), (last, "end"))
    )


def _x(index: int, count: int) -> float:
    """Where the observation at ``index`` of ``count`` sits across the chart."""
    return PADDING + index * (WIDTH - 2 * PADDING) / (count - 1)


def _y(value: int, low: int, high: int) -> float:
    """Where ``value`` sits up the chart of a field spanning ``low`` to ``high``.

    A field that never moved has no span to place it on, and sits halfway up.
    """
    if high == low:
        return HEIGHT / 2
    return HEIGHT - PADDING - (value - low) / (high - low) * (HEIGHT - 2 * PADDING)
