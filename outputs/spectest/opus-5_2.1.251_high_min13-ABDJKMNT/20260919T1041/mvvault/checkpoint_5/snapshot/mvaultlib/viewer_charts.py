"""The `views` and `likes` charts of an entry detail page.

Both charts are published twice over: once as JSON, so the points stay
machine-readable whatever version the vault declares, and once as a polyline
drawn from the same points. The JSON keeps every point exactly as the vault
recorded it - including the `null` a `likes` history may hold - and only the
timestamps are normalized, from whatever key format the version uses to ISO
8601. A history holding a single point has nothing to draw between, so its
drawing is left out while its data stays.
"""

import json

from . import vault_view

#: The tracked fields charted on a detail page.
CHART_FIELDS = ("views", "likes")

#: Identifies the embedded payload for anything reading the page as data.
PAYLOAD_ID = "chart-data"

#: Drawing area of one chart, in SVG user units.
WIDTH, HEIGHT = 480, 120


def section(entry, view):
    """The chart block of a detail page: the point data plus its drawings."""
    charted = {field: points(entry, field, view) for field in CHART_FIELDS}
    drawings = "".join(_drawing(field, charted[field]) for field in CHART_FIELDS)
    return (
        f'<script id="{PAYLOAD_ID}" type="application/json">{_payload(charted)}</script>\n'
        f'<div class="charts">{drawings}</div>'
    )


def points(entry, field, view):
    """One history as ISO-stamped points, oldest first, with nothing dropped."""
    return [
        {"timestamp": view.key_to_iso(key), "value": value}
        for key, value in vault_view.ordered_items(entry, field, view)
    ]


def _payload(charted):
    """The points as JSON that cannot close the script element it sits in."""
    return json.dumps(charted).replace("<", "\\u003c")


def _drawing(field, charted):
    """One field's polyline, omitted when there are fewer than two points to join."""
    plotted = [(index, point["value"]) for index, point in enumerate(charted) if point["value"] is not None]
    if len(charted) < 2 or len(plotted) < 2:
        return ""

    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in _positions(plotted, len(charted) - 1))
    return (
        f'<svg class="chart {field}" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'role="img" aria-label="{field} over time"><polyline points="{line}"/></svg>'
    )


def _positions(plotted, span):
    """Plot positions filling the drawing area, oldest point at the left."""
    values = [value for _, value in plotted]
    spread = (max(values) - min(values)) or 1
    return [(index * WIDTH / span, HEIGHT - (value - min(values)) * HEIGHT / spread) for index, value in plotted]
