"""The HTML the viewer serves: the landing page, category listings and entry pages."""

from html import escape

from . import vault_view, viewer_assets, viewer_charts, viewer_links

STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 48rem; }
ul { list-style: none; padding: 0; }
li.entry { padding: .35rem .5rem; border-bottom: 1px solid #ddd; }
li.entry.missing a { color: #666; }
li.entry.removed a { text-decoration: line-through; }
.badge { font-size: .75rem; margin-left: .5rem; padding: .1rem .4rem; border-radius: .6rem; background: #eee; }
.badge.downloaded { background: #d6f0d6; }
.badge.missing { background: #eee; }
.badge.removed { background: #f6d6d6; }
.not-found { color: #a00; }
nav a { margin-right: .75rem; }
.files img, .files video { max-width: 100%; }
dl.facts dt { font-weight: 600; margin-top: .5rem; }
svg.chart { width: 100%; height: 8rem; background: #fafafa; border: 1px solid #ddd; }
svg.chart polyline { fill: none; stroke: #2a6; stroke-width: 2; }
"""


def landing(recent, missing=None):
    """The `/` page: the vault form, a not-found notice and recent vaults."""
    body = [
        "<h1>mvault</h1>",
        _notice(missing),
        '<form method="post" action="/">',
        '<label for="catalog">Vault name</label>',
        '<input id="catalog" name="catalog" type="text" autofocus>',
        '<button type="submit">Open</button>',
        "</form>",
        _recent_list(recent),
    ]
    return _page("mvault", body)


def listing(name, view, category):
    """A category listing: one row per entry, in catalog order."""
    entries = view.entries_of(category)
    downloaded = viewer_assets.downloaded_ids(name, [entry["id"] for entry in entries])
    body = [
        f"<h1>{escape(name)} / {escape(category)}</h1>",
        _category_nav(name, view, category),
        _entry_list([_row(name, category, entry, view, downloaded) for entry in entries]),
        '<p><a href="/">All vaults</a></p>',
    ]
    return _page(f"{name} / {category}", body)


def detail(name, view, category, entry):
    """One entry's page: its current metadata, the vault's files and its charts."""
    body = [
        f"<h1>{escape(vault_view.current_title(entry, view))}</h1>",
        f'<nav><a href="{viewer_links.catalog_route(name, category)}">Back to {escape(category)}</a></nav>',
        _files(name, entry["id"]),
        f'<p class="description">{escape(vault_view.current_description(entry, view))}</p>',
        _facts(view, entry),
        viewer_charts.section(entry, view),
        '<p><a href="/">All vaults</a></p>',
    ]
    return _page(f"{name} / {category} / {entry['id']}", body)


def error(message):
    """A plain page for a request the viewer cannot answer."""
    return _page("mvault", ["<h1>mvault</h1>", f'<p class="error">{escape(message)}</p>'])


def _files(name, entry_id):
    """The vault's own copies of the entry, each shown only while it is there."""
    shown = []
    if viewer_assets.preview_name(name, entry_id):
        source = viewer_links.vault_route(name, viewer_links.PREVIEW_SEGMENT, entry_id)
        shown.append(f'<img class="preview" src="{source}" alt="">')

    media = viewer_assets.media_name(name, entry_id)
    if media:
        source = viewer_links.vault_route(name, viewer_links.MEDIA_SEGMENT, media)
        shown.append(f'<video class="media" controls src="{source}"></video>')
    else:
        shown.append('<p class="no-media">No downloaded media.</p>')

    return f'<div class="files">{"".join(shown)}</div>'


def _facts(view, entry):
    """The entry's static metadata and the link back to the source platform."""
    source = viewer_links.source_entry_url(view.source, entry["id"])
    return (
        '<dl class="facts">'
        f'<dt>Published</dt><dd class="published">{escape(entry["published"])}</dd>'
        f'<dt>Dimensions</dt><dd class="dimensions">{entry["width"]} × {entry["height"]}</dd>'
        f'<dt>Source</dt><dd><a class="source" href="{escape(source)}">{escape(source)}</a></dd>'
        "</dl>"
    )


def _entry_list(rows):
    """The listing's rows, or a word about the category being empty."""
    if not rows:
        return '<p class="empty">No entries.</p>'
    return '<ul class="entries">\n' + "\n".join(rows) + "\n</ul>"


def _row(name, category, entry, view, downloaded):
    """One entry, marked with the states the listing has to distinguish."""
    entry_id = entry["id"]
    states = ["downloaded" if entry_id in downloaded else "missing"]
    if vault_view.is_removed(entry, view):
        states.append("removed")

    badges = "".join(f'<span class="badge {state}">{state}</span>' for state in states)
    href = viewer_links.catalog_route(name, category, entry_id)
    title = escape(vault_view.current_title(entry, view))
    return f'<li class="entry {" ".join(states)}"><a href="{href}">{title}</a>{badges}</li>'


def _category_nav(name, view, current):
    """Links to the other categories this vault's version has."""
    links = [
        f'<a href="{viewer_links.catalog_route(name, category)}">{escape(category)}</a>'
        if category != current
        else f"<strong>{escape(category)}</strong>"
        for category, _ in view.categories
    ]
    return f"<nav>{''.join(links)}</nav>"


def _recent_list(recent):
    """The recent-vaults area, left out entirely while nothing was visited."""
    if not recent:
        return ""
    items = [f'<li><a href="{route}">{escape(name)}</a></li>' for name, route in recent]
    return '<h2>Recent vaults</h2>\n<ul class="recent">\n' + "\n".join(items) + "\n</ul>"


def _notice(missing):
    """The vault-not-found line, shown after a bounce from `/catalog`."""
    return f'<p class="not-found">Vault \'{escape(missing)}\' was not found.</p>' if missing else ""


def _page(title, body):
    """One complete document around `body`."""
    parts = "\n".join(part for part in body if part)
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="utf-8">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head>\n"
        f"<body>\n{parts}\n</body>\n</html>\n"
    )
