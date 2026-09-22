"""The viewer's HTML: the landing page, category listings, entry detail pages,
and error pages."""

from html import escape

from .charts import chart_payload, is_chartable
from .links import category_path, entry_path, media_path, preview_path

#: Page styling, deliberately free of any state name, so that a word such as
#: "downloaded" appears on a page only where an entry is really in that state.
STYLE = (
    "body{font-family:system-ui,sans-serif;margin:2rem;max-width:52rem;color:#222}"
    "h1{font-size:1.4rem}"
    "ul{list-style:none;padding:0}"
    "li{padding:.35rem .5rem;border-bottom:1px solid #eee}"
    "nav a{margin-right:1rem}"
    ".badge{font-size:.78rem;padding:.05rem .45rem;border-radius:.6rem;margin-left:.5rem}"
    ".notice{background:#fdecea;padding:.5rem .75rem;border-radius:.4rem}"
    "dt{font-weight:600;margin-top:.5rem}"
    "dd{margin:0}"
    "video,img.preview{max-width:100%;border-radius:.4rem}"
    "figure{margin:1rem 0}"
    "figcaption{font-size:.85rem;color:#555}"
    ".chart{border:1px solid #eee;border-radius:.4rem;padding:.5rem}"
)

#: Size of a chart's drawing area, in the user units its polyline is plotted in.
CHART_WIDTH = 480
CHART_HEIGHT = 120

#: Inline styling for the states a listing row can be in.
FETCHED_BADGE = "background:#e6f4ea;color:#14532d"
PENDING_BADGE = "background:#eeeeee;color:#555555"
GONE_BADGE = "background:#fdecea;color:#7f1d1d"
GONE_ROW = "text-decoration:line-through"


def landing_page(recent, missing=None):
    """The landing page: the vault-name form, plus where this browser has been.

    `recent` pairs each remembered vault with the path its link opens, and
    `missing` names a vault the viewer was asked for and could not find.
    """
    return _document(
        "mvault viewer",
        [
            "<h1>mvault viewer</h1>",
            _missing_notice(missing),
            _vault_form(),
            _recent_list(recent),
        ],
    )


def category_page(listing):
    """One category listing, in the order the catalog stores its entries."""
    heading = f"{listing.name} / {listing.category}"
    return _document(
        f"{heading} - mvault",
        [
            f'<p><a href="/">mvault viewer</a> - catalog version {listing.version}</p>',
            f"<h1>{escape(heading)}</h1>",
            _category_nav(listing),
            _entry_list(listing),
        ],
    )


def entry_page(detail):
    """One entry's detail page: its metadata, its media, and its chart data."""
    return _document(
        f"{detail.title} - mvault",
        [
            _detail_nav(detail),
            f"<h1>{escape(detail.title)}</h1>",
            f"<p>{escape(detail.description)}</p>",
            _metadata(detail),
            _preview(detail),
            _media(detail),
            _charts(detail),
        ],
    )


def error_page(message):
    """The page any request that cannot be answered gets instead."""
    return _document(
        "mvault viewer",
        [
            "<h1>mvault viewer</h1>",
            f'<p class="notice">{escape(message)}</p>',
            '<p><a href="/">Back to the vault list</a></p>',
        ],
    )


def _detail_nav(detail):
    """Back to the listing this entry was reached through, and to the vault list."""
    listing = category_path(detail.name, detail.category)
    return (
        f'<p><a href="/">mvault viewer</a> - '
        f'<a href="{listing}">back to {escape(detail.category)}</a></p>'
    )


def _metadata(detail):
    """The entry's published date, pixel size, and place on the source platform."""
    return (
        "<dl>\n"
        f"<dt>Published</dt><dd>{escape(detail.published)}</dd>\n"
        f'<dt>Dimensions</dt><dd data-width="{detail.width}" data-height="{detail.height}">'
        f"{detail.width} &times; {detail.height}</dd>\n"
        f'<dt>Source</dt><dd><a href="{escape(detail.source)}">'
        f"{escape(detail.source)}</a></dd>\n"
        "</dl>"
    )


def _preview(detail):
    """The saved preview image, when the vault has downloaded one."""
    if not detail.has_preview:
        return ""
    source = preview_path(detail.name, detail.entry_id)
    return f'<img class="preview" src="{source}" alt="{escape(detail.title)}">'


def _media(detail):
    """A player for the downloaded media file, named exactly as it was saved."""
    if detail.media_file is None:
        return "<p>This entry has no media file here.</p>"
    source = media_path(detail.name, detail.media_file)
    return f'<video controls src="{source}"></video>'


def _charts(detail):
    """The chart data, embedded for machines and drawn for the fields worth it."""
    figures = [
        _chart(field, points)
        for field, points in detail.charts.items()
        if is_chartable(points)
    ]
    embedded = (
        f'<script type="application/json" id="chart-data">'
        f"{chart_payload(detail.charts)}</script>"
    )
    return "\n".join([*figures, embedded])


def _chart(field, points):
    """One field's history as a polyline, oldest point on the left."""
    values = [point.value for point in points if point.value is not None]
    line = " ".join(
        f"{_across(index, points)},{_up(point.value, values)}"
        for index, point in enumerate(points)
        if point.value is not None
    )
    return (
        f'<figure class="chart" data-chart="{field}">\n'
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img">'
        f'<polyline fill="none" stroke="#2b6cb0" stroke-width="2" points="{line}"/>'
        "</svg>\n"
        f"<figcaption>{field}: {points[0].timestamp} to {points[-1].timestamp}"
        f"</figcaption>\n</figure>"
    )


def _across(index, points):
    """Where a point sits horizontally: its position among the points."""
    return round(index * CHART_WIDTH / (len(points) - 1), 1)


def _up(value, values):
    """Where a value sits vertically, with the largest at the top of the box."""
    span = max(values) - min(values)
    return round(CHART_HEIGHT * (1 - (value - min(values)) / span if span else 0.5), 1)


def _vault_form():
    """The form that takes a vault name and posts it back to the landing page."""
    return (
        '<form method="post" action="/">\n'
        '<label for="catalog">Vault name</label>\n'
        '<input id="catalog" name="catalog" type="text" autofocus>\n'
        '<button type="submit">Open</button>\n'
        "</form>"
    )


def _missing_notice(missing):
    """Says which vault the viewer was sent to and could not find."""
    if not missing:
        return ""
    return f'<p class="notice">Vault <code>{escape(missing)}</code> was not found.</p>'


def _recent_list(recent):
    """The recently visited vaults, most recent first; absent when there are none."""
    if not recent:
        return ""
    items = [
        f'<li><a href="{path}">{escape(name)}</a></li>' for name, path in recent
    ]
    return "<h2>Recent vaults</h2>\n<ul>\n" + "\n".join(items) + "\n</ul>"


def _category_nav(listing):
    """Links to the other categories this vault's version has."""
    links = [
        f'<a href="{category_path(listing.name, category)}">{escape(category)}</a>'
        for category in listing.categories
    ]
    return f"<nav>{''.join(links)}</nav>"


def _entry_list(listing):
    """The category's entries, in stored order."""
    if not listing.rows:
        return "<p>This category has no entries.</p>"
    return "<ul>\n" + "\n".join(_entry_row(listing, row) for row in listing.rows) + "\n</ul>"


def _entry_row(listing, row):
    """One entry: its link, whether its media is here, and whether it is gone."""
    classes = ["entry", "downloaded" if row.downloaded else "pending"]
    badges = [
        _badge("downloaded", FETCHED_BADGE)
        if row.downloaded
        else _badge("not fetched", PENDING_BADGE)
    ]
    styles = []
    if row.removed:
        classes.append("removed")
        badges.append(_badge("removed", GONE_BADGE))
        styles.append(GONE_ROW)

    target = entry_path(listing.name, listing.category, row.entry_id)
    style = f' style="{";".join(styles)}"' if styles else ""
    return (
        f'<li class="{" ".join(classes)}"{style}>'
        f'<a href="{target}">{escape(row.title)}</a>{"".join(badges)}</li>'
    )


def _badge(text, style):
    return f'<span class="badge" style="{style}">{text}</span>'


def _document(title, blocks):
    """A complete HTML document from the blocks that have something to say."""
    body = "\n".join(block for block in blocks if block)
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )
