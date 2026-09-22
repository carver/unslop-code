"""The entry detail page: one entry's current metadata, its files, the
annotations it stores, and its charts.

Everything shown is resolved through the catalog view, so a v1, v2 or v3 vault
produces the same page from the layout it happens to be stored in; annotations
are a version 3 field, so a legacy entry simply has none to show.
"""

import re
from html import escape

from .annotations import ANNOTATIONS_FIELD
from .charts import charts
from .pages import document
from .viewer import asset_route, catalog_route

#: A `?timecode=` the page can seek to: whole seconds, as a create redirect sends.
WHOLE_SECONDS = re.compile(r"[0-9]+")


def detail_page(name, view, category, entry, stored, timecode=None):
    """Everything the viewer knows about one entry, on one page.

    `timecode` is the `?timecode=` query the page was asked for: the second
    playback starts at, which is how a created annotation returns to its entry.
    """
    entry_id = entry["id"]
    seek = timecode if timecode and WHOLE_SECONDS.fullmatch(timecode) else None
    parts = [
        heading(view, entry),
        metadata(view, entry),
        seek_notice(seek),
        files(name, entry_id, stored, seek),
        annotation_list(entry),
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


def seek_notice(seek):
    """Where playback starts, on a page that was asked to seek."""
    return f'<p class="seek">Playback starts at {seek} seconds.</p>' if seek else ""


def files(name, entry_id, stored, seek):
    """The saved preview and media player, addressed through `/vault`."""
    parts = []
    if stored.preview:
        source = asset_route(name, "preview", entry_id)
        parts.append(f'<img class="preview" src="{source}" alt="Saved preview image">')
    if stored.media:
        source = media_source(name, stored.media, seek)
        parts.append(f'<video class="media" controls src="{source}"></video>')
    return "\n".join(parts) if parts else '<p class="no-media">No media downloaded.</p>'


def media_source(name, media, seek):
    """The media file's `/vault` address, starting where the page was asked to.

    A media fragment is how a browser is told where to begin playing a file it
    is handed directly.
    """
    route = asset_route(name, "media", media)
    return f"{route}#t={seek}" if seek else route


def annotation_list(entry):
    """The entry's stored annotations, in the order the catalog keeps them."""
    stored = entry.get(ANNOTATIONS_FIELD) or []
    if not stored:
        return ""

    items = "\n".join(annotation_item(annotation) for annotation in stored)
    return f'<h2>Annotations</h2>\n<ul class="annotations">\n{items}\n</ul>'


def annotation_item(annotation):
    """One annotation: its timecode as raw seconds, its title, and its body."""
    body = annotation.get("body")
    text = f'\n<p class="annotation-body">{escape(str(body))}</p>' if body else ""
    return (
        '<li class="annotation">'
        f'<span class="timecode">{escape(str(annotation["timecode"]))}</span> '
        f'<span class="annotation-title">{escape(str(annotation["title"]))}</span>'
        f"{text}</li>"
    )
