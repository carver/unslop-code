"""HTML rendering of the viewer pages.

Every page is a self-contained document: the styles that tell the entry states
apart travel with it, so the server never has to serve assets of its own.
"""

import json
from html import escape

from . import annotations, charts, viewer

STYLE = """
body { font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 48rem; color: #1b1b1b; }
a { color: #14568c; }
nav a { margin-right: 1rem; }
nav a.current { font-weight: 700; text-decoration: none; }
ul { list-style: none; padding: 0; }
li.entry { border-left: 4px solid #cfcfcf; padding: .4rem .8rem; margin: .3rem 0; }
li.downloaded { border-left-color: #1f7a3f; background: #f2fbf5; }
li.pending { border-left-color: #cfcfcf; background: #fafafa; }
li.removed a { text-decoration: line-through; }
li.removed { opacity: .65; }
.state, .flag { font-size: .8rem; margin-left: .6rem; text-transform: uppercase; }
.state { color: #4a4a4a; }
.flag { color: #a11; }
.missing { background: #fdf0f0; border-left: 4px solid #a11; padding: .6rem .8rem; }
dt { font-weight: 700; }
dd { margin: 0 0 .4rem; }
.media { display: block; max-width: 100%; margin: 1rem 0; background: #1b1b1b; }
ol.annotations { list-style: none; padding: 0; }
li.annotation { border-left: 4px solid #14568c; padding: .4rem .8rem; margin: .3rem 0; }
li.annotation { background: #f6f9fc; }
li.annotation .timecode { font-variant-numeric: tabular-nums; font-weight: 700; }
.annotation-body { margin: .2rem 0 0; }
li.annotation form, li.annotation details { display: inline-block; margin-right: .6rem; }
form.annotate { margin: .6rem 0; }
""" + charts.CHART_STYLE


#: The form creating an annotation on the entry the page shows.
ANNOTATION_FORM = (
    '<form class="annotate" data-annotate="POST">'
    '<input name="title" placeholder="Title" required aria-label="Annotation title">'
    '<input name="timecode" placeholder="1:30" required aria-label="Timecode">'
    '<input name="body" placeholder="Note" aria-label="Annotation body">'
    '<button type="submit">Add annotation</button></form>'
)

#: Sends every annotation form as the JSON request its method expects, then follows
#: the redirect the viewer answers with, so the page shows what was stored.
ANNOTATION_SCRIPT = """
for (const form of document.querySelectorAll('[data-annotate]')) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const answer = await fetch(location.pathname, {
      method: form.dataset.annotate,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    if (answer.redirected) { location.assign(answer.url); return; }
    document.documentElement.innerHTML = await answer.text();
  });
}
"""


def landing(recent, missing):
    """The landing page: the vault form, any vault-not-found notice and recent vaults."""
    body = [
        "<h1>mvault viewer</h1>",
        _missing_notice(missing),
        '<form method="post" action="/">',
        '<label for="catalog">Vault name</label> ',
        '<input id="catalog" name="catalog" autofocus>',
        '<button type="submit">Open</button>',
        "</form>",
        _recent_section(recent),
    ]
    return _document("mvault viewer", body)


def listing(name, category, rows, categories):
    """A category listing: every entry with its state and a link to its own page."""
    heading = f"{escape(name)} / {escape(category)}"
    body = [
        f'<h1><a href="/">mvault</a> / {heading}</h1>',
        _navigation(name, category, categories),
        f'<ul class="entries">{"".join(_row(name, category, row) for row in rows)}</ul>',
    ]
    return _document(f"{name} - {category}", body)


def detail(name, category, entry):
    """An entry page: its current metadata, its stored media and its tracked histories."""
    back = escape(viewer.category_path(name, category), quote=True)
    body = [
        f'<h1><a href="/">mvault</a> / {escape(name)} / {escape(category)}</h1>',
        f'<p><a href="{back}">&larr; Back to {escape(category)}</a></p>',
        f"<h2>{escape(entry.title)}</h2>",
        f'<p class="description">{escape(entry.description)}</p>',
        _facts(entry),
        _media(entry),
        _annotations(entry.annotations),
        _charts(entry.charts),
    ]
    return _document(f"{name} - {entry.title}", body)


def error(status, message):
    """The page answering a request the viewer refused, saying what was wrong with it."""
    body = [
        f"<h1>{escape(status.phrase)}</h1>",
        f"<p>{escape(message)}</p>",
        '<p><a href="/">Back to the vault list</a></p>',
    ]
    return _document(status.phrase, body)


def not_found(path):
    """The page answering a request for a route the viewer does not serve."""
    body = [
        "<h1>Not found</h1>",
        f"<p>The viewer serves no page at {escape(path)}.</p>",
        '<p><a href="/">Back to the vault list</a></p>',
    ]
    return _document("Not found", body)


def forbidden(path):
    """The page answering a request that tried to reach outside the vault directory."""
    body = [
        "<h1>Forbidden</h1>",
        f"<p>The viewer serves nothing outside a vault's own files: {escape(path)}.</p>",
        '<p><a href="/">Back to the vault list</a></p>',
    ]
    return _document("Forbidden", body)


def _document(title, body):
    """Wrap rendered body markup in the shared page shell."""
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head>\n"
        f'<body>{"".join(body)}</body></html>\n'
    )


def _missing_notice(missing):
    """Report a vault the viewer could not open, when a redirect named one."""
    if not missing:
        return ""
    return f'<p class="missing">Vault not found: {escape(missing)}</p>'


def _recent_section(recent):
    """List the recently visited vaults, each linking to its default category page."""
    if not recent:
        return ""
    items = "".join(
        f'<li><a href="{escape(path, quote=True)}">{escape(name)}</a></li>' for name, path in recent
    )
    return f'<h2>Recent vaults</h2><ul class="recent">{items}</ul>'


def _navigation(name, current, categories):
    """Link the categories of the vault, marking the one being listed."""
    links = []
    for category in categories:
        mark = ' class="current"' if category == current else ""
        href = escape(viewer.category_path(name, category), quote=True)
        links.append(f"<a{mark} href=\"{href}\">{escape(category)}</a>")
    return f"<nav>{''.join(links)}</nav>"


def _row(name, category, row):
    """Render one entry: its title link, its download state and its removal flag."""
    classes = ["entry", "downloaded" if row.downloaded else "pending"]
    if row.removed:
        classes.append("removed")
    href = escape(viewer.entry_path(name, category, row.id), quote=True)
    flag = '<span class="flag">removed</span>' if row.removed else ""
    return (
        f'<li class="{" ".join(classes)}" id="entry-{escape(row.id, quote=True)}">'
        f'<a href="{href}">{escape(row.title)}</a>'
        f'<span class="state">{"downloaded" if row.downloaded else "not downloaded"}</span>'
        f"{flag}</li>"
    )


def _facts(entry):
    """The metadata list: the publication date, the dimensions and the source-platform link."""
    href = escape(entry.source_link, quote=True)
    return (
        "<dl>"
        f"<dt>Published</dt><dd>{escape(entry.published)}</dd>"
        f"<dt>Dimensions</dt><dd>{entry.width} &times; {entry.height}</dd>"
        f'<dt>Source</dt><dd><a href="{href}">{escape(entry.source_link)}</a></dd>'
        "</dl>"
    )


def _media(entry):
    """Play the downloaded media, or show the preview image and say what is missing."""
    if entry.media_url:
        poster = f' poster="{escape(entry.preview_url, quote=True)}"' if entry.preview_url else ""
        source = escape(_playback_url(entry), quote=True)
        return f'<video class="media" controls{poster} src="{source}"></video>'
    preview = (
        f'<img class="media" src="{escape(entry.preview_url, quote=True)}" alt="Preview image">'
        if entry.preview_url
        else ""
    )
    return f'{preview}<p class="state">media not downloaded</p>'


def _playback_url(entry):
    """Address of the stored media, as a media fragment when the page opens at a timecode."""
    if entry.seek is None:
        return entry.media_url
    return f"{entry.media_url}#t={entry.seek}"


def _annotations(marked):
    """The annotations of an entry, in stored order, and the forms that manage them."""
    items = "".join(_annotation(annotation) for annotation in marked)
    empty = '<p class="state">no annotations</p>'
    listing = f'<ol class="annotations">{items}</ol>' if items else empty
    return (
        f"<h3>Annotations</h3>{listing}{ANNOTATION_FORM}"
        f"<script>{ANNOTATION_SCRIPT}</script>"
    )


def _annotation(annotation):
    """One annotation: a link opening the media at its timecode, its text and its forms."""
    seek = escape(f"?{viewer.TIMECODE_PARAM}={annotation.timecode}", quote=True)
    body = f'<p class="annotation-body">{escape(annotation.body)}</p>' if annotation.body else ""
    return (
        f'<li class="annotation" id="annotation-{escape(annotation.id, quote=True)}">'
        f'<a class="timecode" href="{seek}">{escape(annotation.label)}</a> '
        f'<span class="annotation-title">{escape(annotation.title)}</span>{body}'
        f"{_annotation_forms(annotation)}</li>"
    )


def _annotation_forms(annotation):
    """The forms replacing one annotation's text and deleting it, both naming its id."""
    names = f'<input type="hidden" name="id" value="{escape(annotation.id, quote=True)}">'
    fields = "".join(
        f'<input name="{field}" value="{escape(getattr(annotation, field), quote=True)}" '
        f'aria-label="Annotation {field}">'
        for field in annotations.EDITABLE_FIELDS
    )
    return (
        f'<details><summary>Edit</summary><form data-annotate="PATCH">{names}{fields}'
        '<button type="submit">Save</button></form></details>'
        f'<form data-annotate="DELETE">{names}'
        '<button type="submit">Delete</button></form>'
    )


def _charts(charted):
    """Draw one figure per charted field and embed the same points for machines to read."""
    if not charted:
        return ""
    figures = "".join(charts.figure(field, points) for field, points in charted.items())
    return (
        f"<h3>Tracked history</h3>{figures}"
        f'<script type="application/json" id="chart-data">{_payload(charted)}</script>'
    )


def _payload(charted):
    """Serialize the chart points, keeping the JSON from closing the script element."""
    return json.dumps(charted).replace("<", "\\u003c")
