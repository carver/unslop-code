"""HTML for the viewer's pages: the landing page, a category listing and an
entry detail page."""

import json
from html import escape

from mvaultlib.viewer.charts import chart_payload, plot_points
from mvaultlib.viewer.links import MEDIA_ENDPOINT, PREVIEW_ENDPOINT, asset_path, catalog_path

STYLE = """
body { font-family: system-ui, sans-serif; max-width: 48rem; margin: 2rem auto; }
h1 { font-size: 1.4rem; }
nav a { margin-right: .75rem; }
ul.entries { list-style: none; padding: 0; }
li.entry { padding: .35rem .5rem; border-left: 4px solid #2f6feb; }
li.pending { border-left-color: #c9ced6; }
li.pending a { color: #5b6270; }
li.removed { border-left-color: #b3261e; text-decoration: line-through; }
span.badge { font-size: .8rem; color: #5b6270; margin-left: .5rem; }
p.notice { background: #fdeceb; border-left: 4px solid #b3261e; padding: .5rem; }
dl.meta { display: grid; grid-template-columns: 8rem 1fr; gap: .2rem 1rem; }
dl.meta dt { color: #5b6270; }
figure.chart { margin: 1rem 0; }
figure.chart svg { border-bottom: 1px solid #c9ced6; }
figure.chart polyline { fill: none; stroke: #2f6feb; stroke-width: 2; }
video, img.preview { max-width: 100%; }
"""

#: Drawing box of an inline chart, in SVG user units.
CHART_WIDTH = 480
CHART_HEIGHT = 120


def page(title, body):
    """Wrap rendered body markup in the viewer's minimal HTML document."""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def landing_page(recent, missing=None):
    """The vault-name form, the vault-not-found notice and the recent vaults.

    `recent` holds `(name, path)` pairs, newest first, where each path is the
    vault's resolved default category page.
    """
    sections = ["<h1>mvault viewer</h1>"]
    if missing is not None:
        sections.append(f'<p class="notice">Vault "{escape(missing)}" was not found.</p>')
    sections.append(
        '<form method="post" action="/">\n'
        '<label for="catalog">Vault name</label>\n'
        '<input id="catalog" name="catalog" autofocus>\n'
        '<button type="submit">Open</button>\n</form>'
    )
    sections.append(_recent_section(recent))
    return page("mvault viewer", "\n".join(section for section in sections if section))


def category_page(name, view, group, entries):
    """One category listing: its entries in catalog order, states marked."""
    rows = "\n".join(_entry_row(name, group.category, entry) for entry in entries)
    body = (
        f"<h1>{escape(name)} &mdash; {escape(group.label)}</h1>\n"
        f'<p>Catalog version {view.version}. <a href="/">All vaults</a></p>\n'
        f"{_category_nav(name, view, group.category)}\n"
        f'<ul class="entries">\n{rows}\n</ul>'
    )
    return page(f"{name} - {group.label}", body)


def _recent_section(recent):
    """The recently visited vaults, or nothing at all when none were visited."""
    if not recent:
        return ""
    links = "\n".join(
        f'<li><a href="{escape(path)}">{escape(name)}</a></li>' for name, path in recent
    )
    return f"<h2>Recent vaults</h2>\n<ul>\n{links}\n</ul>"


def _category_nav(name, view, current):
    """Links to the sibling categories this vault version offers."""
    links = " ".join(
        f'<a href="{catalog_path(name, group.category)}">{escape(group.label)}</a>'
        if group.category != current
        else f"<strong>{escape(group.label)}</strong>"
        for group in view.groups
    )
    return f"<nav>{links}</nav>"


def _entry_row(name, category, entry):
    """One entry, on a single line, carrying its state in classes and badges."""
    classes = ["entry", "downloaded" if entry.downloaded else "pending"]
    badges = ["downloaded" if entry.downloaded else "not downloaded"]
    if entry.removed:
        classes.append("removed")
        badges.append("removed")
    link = catalog_path(name, category, entry.entry_id)
    marks = "".join(f'<span class="badge">{badge}</span>' for badge in badges)
    return (
        f'<li class="{" ".join(classes)}" data-entry="{escape(entry.entry_id)}">'
        f'<a href="{link}">{escape(entry.title)}</a>{marks}</li>'
    )


def entry_page(name, view, group, detail):
    """One entry detail page: its metadata, its stored media and its charts."""
    body = "\n".join(
        section
        for section in (
            f"<h1>{escape(detail.title)}</h1>",
            f'<nav><a href="{catalog_path(name, group.category)}">'
            f"Back to {escape(group.label)}</a></nav>",
            f"<p>{escape(detail.description)}</p>",
            _media_section(name, detail),
            _metadata(view, detail),
            _charts(detail),
        )
        if section
    )
    return page(f"{name} - {detail.title}", body)


def _media_section(name, detail):
    """The stored media and preview of an entry, each shown when it exists."""
    parts = []
    if detail.media_file:
        source = asset_path(name, MEDIA_ENDPOINT, detail.media_file)
        parts.append(f'<video controls src="{source}"></video>')
    if detail.has_preview:
        preview = asset_path(name, PREVIEW_ENDPOINT, detail.entry_id)
        parts.append(f'<img class="preview" src="{preview}" alt="{escape(detail.title)} preview">')
    return "\n".join(parts)


def _metadata(view, detail):
    """The entry's published date, dimensions, id and source-platform link."""
    rows = {
        "Published": escape(detail.published),
        "Dimensions": f"{detail.width} &times; {detail.height}",
        "Entry id": escape(detail.entry_id),
        "Catalog version": str(view.version),
        "On source": f'<a href="{escape(detail.source_link)}">{escape(detail.source_link)}</a>',
    }
    items = "\n".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows.items())
    return f'<dl class="meta">\n{items}\n</dl>'


def _charts(detail):
    """The embedded chart data, and a drawn line for each chartable series."""
    drawn = [_chart_figure(series) for series in detail.series]
    payload = _script_json(chart_payload(detail.entry_id, detail.series))
    embedded = f'<script type="application/json" id="chart-data">{payload}</script>'
    return "\n".join([embedded, *(figure for figure in drawn if figure)])


def _script_json(payload):
    """`payload` as JSON that is safe to embed in a script element.

    A script element holds raw text, so the JSON is not HTML-escaped; only `<`
    is written as an escape, which keeps the text from closing the element
    early while leaving it valid JSON.
    """
    return json.dumps(payload).replace("<", "\\u003c")


def _chart_figure(series):
    """One series as an inline SVG line, or nothing when it cannot be drawn."""
    coordinates = plot_points(series.points, CHART_WIDTH, CHART_HEIGHT)
    if not coordinates:
        return ""
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
    return (
        f'<figure class="chart" data-field="{series.field}">\n'
        f'<figcaption>{escape(series.field)}</figcaption>\n'
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img" '
        f'aria-label="{escape(series.field)} over time">'
        f'<polyline points="{line}"></polyline></svg>\n</figure>'
    )
