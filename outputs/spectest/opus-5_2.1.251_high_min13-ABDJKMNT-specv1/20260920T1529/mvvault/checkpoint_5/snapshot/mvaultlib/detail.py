"""The entry detail page: one entry's current metadata, its files, its charts.

Everything shown is resolved through the catalog view, so a v1, v2 or v3 vault
produces the same page from the layout it happens to be stored in.
"""

from html import escape

from .charts import charts
from .pages import document
from .viewer import asset_route, catalog_route


def detail_page(name, view, category, entry, stored):
    """Everything the viewer knows about one entry, on one page."""
    entry_id = entry["id"]
    parts = [
        heading(view, entry),
        metadata(view, entry),
        files(name, entry_id, stored),
        charts(view, entry),
        f'<p><a href="{catalog_route(name, category)}">Back to {escape(category)}</a></p>',
    ]
    return document(f"{name} / {category} / {entry_id}", "\n".join(part for part in parts if part))


def heading(view, entry):
    """The current title, marked when the vault records the entry as removed."""
    title = escape(view.current(entry, "title"))
    if view.detects_removals and view.current(entry, "removed"):
        return f'<h1>{title} <span class="badge">removed</span></h1>'
    return f"<h1>{title}</h1>"


def metadata(view, entry):
    """The current description, and the facts that do not change: when it was
    published, how big it is, and where it came from."""
    link = escape(view.source_link(entry["id"]))
    published = escape(str(entry["published"]))
    dimensions = escape(f"{entry['width']} × {entry['height']}")
    return (
        f'<p class="description">{escape(view.current(entry, "description"))}</p>\n'
        '<dl class="metadata">\n'
        f"<dt>Published</dt><dd>{published}</dd>\n"
        f"<dt>Dimensions</dt><dd>{dimensions}</dd>\n"
        f'<dt>Source</dt><dd><a href="{link}">{link}</a></dd>\n'
        "</dl>"
    )


def files(name, entry_id, stored):
    """The saved preview and media player, addressed through `/vault`."""
    parts = []
    if stored.preview:
        source = asset_route(name, "preview", entry_id)
        parts.append(f'<img class="preview" src="{source}" alt="Saved preview image">')
    if stored.media:
        source = asset_route(name, "media", stored.media)
        parts.append(f'<video class="media" controls src="{source}"></video>')
    return "\n".join(parts) if parts else '<p class="no-media">No media downloaded.</p>'
