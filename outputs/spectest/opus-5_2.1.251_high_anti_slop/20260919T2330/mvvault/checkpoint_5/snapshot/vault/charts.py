"""Inline SVG line charts for the tracked-value histories of one entry.

The viewer serves no assets of its own, so a chart has to travel with the page
it belongs to: every figure here is plain SVG plus a table of the same numbers,
so the values stay readable without color. Each figure draws a single field
against time; a history that records ``null`` breaks the line there instead of
drawing through the gap.
"""

from html import escape
from itertools import groupby

from .history import format_timestamp, parse_timestamp

WIDTH = 640
HEIGHT = 160
PADDING = 28
#: Radius of the marker sitting on each observed value.
MARKER_RADIUS = 4

CHART_STYLE = """
figure.chart { margin: 1.5rem 0; }
figure.chart figcaption { font-weight: 700; margin-bottom: .3rem; }
.chart svg { width: 100%; height: auto; }
.chart-line { fill: none; stroke: #14568c; stroke-width: 2; stroke-linejoin: round; }
.chart-point { fill: #14568c; }
.chart-axis { stroke: #cfcfcf; stroke-width: 1; }
.chart-tick { fill: #4a4a4a; font-size: 11px; }
.chart table { border-collapse: collapse; font-size: .85rem; margin-top: .4rem; }
.chart td, .chart th { border-bottom: 1px solid #e4e4e4; text-align: left; }
.chart td, .chart th { padding: .15rem .8rem .15rem 0; }
"""


def figure(field, points):
    """Render one field's history as a captioned chart followed by its data table."""
    label = escape(field.capitalize())
    return (
        f'<figure class="chart"><figcaption>{label}</figcaption>'
        f"{_svg(label, points)}"
        f"<details><summary>Data</summary>{_table(label, points)}</details>"
        "</figure>"
    )


def _svg(label, points):
    """Draw the observed values as a line with a marker on each point."""
    plotted = [(parse_timestamp(point["timestamp"]), point["value"]) for point in points]
    observed = [value for _, value in plotted if value is not None]
    if not observed:
        return ""
    place = _projection(plotted, observed)
    baseline = HEIGHT - PADDING
    return (
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="{label} over time">'
        f'<line class="chart-axis" x1="{PADDING}" y1="{baseline}" '
        f'x2="{WIDTH - PADDING}" y2="{baseline}"/>'
        f"{''.join(_line(run, place) for run in _runs(plotted))}"
        f"{''.join(_marker(moment, value, place) for moment, value in plotted if value is not None)}"
        f'<text class="chart-tick" x="0" y="{PADDING}">{max(observed)}</text>'
        f'<text class="chart-tick" x="0" y="{baseline}">{min(observed)}</text>'
        "</svg>"
    )


def _projection(plotted, observed):
    """Return the function placing a ``(moment, value)`` pair in the drawing area.

    A history whose values never move is centred rather than flattened onto the
    baseline, so a straight line still reads as a straight line.
    """
    start = plotted[0][0].timestamp()
    span = plotted[-1][0].timestamp() - start or 1
    low, high = min(observed), max(observed)
    if low == high:
        low, high = low - 1, high + 1

    def place(moment, value):
        across = (moment.timestamp() - start) / span * (WIDTH - 2 * PADDING)
        up = (value - low) / (high - low) * (HEIGHT - 2 * PADDING)
        return PADDING + across, HEIGHT - PADDING - up

    return place


def _runs(plotted):
    """Split a history into the contiguous stretches of observed values."""
    stretches = groupby(plotted, key=lambda point: point[1] is not None)
    return [list(stretch) for observed, stretch in stretches if observed]


def _line(run, place):
    """Draw one uninterrupted stretch of the history."""
    coordinates = " ".join(f"{x:.1f},{y:.1f}" for x, y in (place(*point) for point in run))
    return f'<polyline class="chart-line" points="{coordinates}"/>'


def _marker(moment, value, place):
    """Draw one observation, labelled for the browser's own hover tooltip."""
    x, y = place(moment, value)
    return (
        f'<circle class="chart-point" cx="{x:.1f}" cy="{y:.1f}" r="{MARKER_RADIUS}">'
        f"<title>{format_timestamp(moment)}: {value}</title></circle>"
    )


def _table(label, points):
    """List the same points as text, for reading the numbers off exactly."""
    rows = "".join(
        f'<tr><td>{escape(point["timestamp"])}</td><td>{_value_text(point["value"])}</td></tr>'
        for point in points
    )
    return (
        f"<table><thead><tr><th>Observed</th><th>{label}</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _value_text(value):
    """Show a value in the table, an unobserved one as a dash rather than a blank."""
    return "&mdash;" if value is None else escape(str(value))
