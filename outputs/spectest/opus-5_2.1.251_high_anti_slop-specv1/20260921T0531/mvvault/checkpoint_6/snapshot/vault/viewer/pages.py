"""The HTML the viewer serves.

Pages are plain server-rendered documents: every state an entry can be in is
both a word in the listing and a class on its row, so it reads the same to a
person and to a stylesheet. Colours live in custom properties, one set per
mode, so the charts of a detail page belong to the same system in light and in
dark.
"""

from html import escape

from .. import links
from . import charts

DOWNLOADED = "downloaded"
UNDOWNLOADED = "missing"
REMOVED = "removed"
NO_MEDIA = "no media downloaded for this entry"
NO_ANNOTATIONS = "no annotations on this entry"

PALETTE = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --ink: #0b0b0b; --ink-soft: #52514e; --grid: #e7e6e2;
  --link: #1c5eb8; --series-views: #2a78d6; --series-likes: #eb6834;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface: #1a1a19; --ink: #ffffff; --ink-soft: #c3c2b7; --grid: #383835;
    --link: #86b6ef; --series-views: #3987e5; --series-likes: #d95926;
  }
}
"""

STYLE = PALETTE + """
body { font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 48rem;
       background: var(--surface); color: var(--ink); }
a { color: var(--link); }
.meta { color: var(--ink-soft); }
.notice { background: #fdf0d5; color: #3d2b00; border-left: 4px solid #c2762a; padding: .5rem .75rem; }
nav a { margin-right: 1rem; }
nav .here { font-weight: 700; text-decoration: none; color: var(--ink); }
ul.entries { list-style: none; padding: 0; }
.entry { border-bottom: 1px solid var(--grid); display: flex; gap: .75rem; padding: .4rem 0; }
.state { color: var(--ink-soft); font-size: .8rem; text-transform: uppercase; }
.entry.missing a { color: var(--ink-soft); }
.entry.removed a { text-decoration: line-through; }
.media { display: block; max-width: 100%; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: .2rem 1rem; }
.facts dt { color: var(--ink-soft); }
.facts dd { margin: 0; }
.chart { margin: 1.5rem 0; }
.chart h2 { color: var(--ink-soft); font-size: .8rem; margin: 0; text-transform: uppercase; }
.chart svg { height: auto; width: 100%; }
.chart .line { fill: none; stroke-linecap: round; stroke-linejoin: round; stroke-width: 2; }
.chart .point { stroke: var(--surface); stroke-width: 2; }
.chart .grid { stroke: var(--grid); stroke-width: 1; }
.chart .tick { fill: var(--ink-soft); font-size: 11px; }
.chart-views .line { stroke: var(--series-views); }
.chart-views .point { fill: var(--series-views); }
.chart-likes .line { stroke: var(--series-likes); }
.chart-likes .point { fill: var(--series-likes); }
ol.annotations { list-style: none; padding: 0; }
.annotation { border-bottom: 1px solid var(--grid); padding: .4rem 0; }
.annotation .timecode { color: var(--ink-soft); font-variant-numeric: tabular-nums; }
.annotation .note { color: var(--ink-soft); margin: .2rem 0 0; }
"""

FORM = (
    f'<form method="post" action="{links.ROOT}">'
    '<label for="catalog">vault</label> '
    '<input id="catalog" name="catalog" autofocus> '
    '<button type="submit">open</button>'
    "</form>"
)


def landing(recent, missing):
    """The landing page: the vault form, and the vaults this browser has seen.

    ``recent`` pairs each remembered vault with its default category page;
    ``missing`` names the vault a redirect here could not find, if any.
    """
    body = ["<h1>mvault</h1>"]
    if missing:
        body.append(f'<p class="notice">No vault named "{escape(missing)}" here.</p>')
    body.append(FORM)
    if recent:
        body.append("<h2>recently viewed</h2>")
        body.append('<ul class="recent">')
        body.extend(f'<li><a href="{path}">{escape(name)}</a></li>' for name, path in recent)
        body.append("</ul>")
    return _document("mvault", body)


def listing(model):
    """One category listing, in catalog order, each entry linking to its page."""
    body = [
        f"<h1>{escape(model.name)}</h1>",
        f'<p class="meta">catalog version {model.version}</p>',
        _navigation(model),
        '<ul class="entries">',
        *(_entry(model, row) for row in model.rows),
        "</ul>",
        f'<p><a href="{links.ROOT}">all vaults</a></p>',
    ]
    return _document(f"{model.name} - {model.category}", body)


def detail(model, timecode=None):
    """One entry's page: what it stores, what it looks like, and how it moved.

    ``timecode`` is the second the page was asked to open the media at, which
    is where a browser sent back from a new annotation lands.
    """
    body = [
        f"<h1>{escape(model.title)}</h1>",
        f'<p class="meta">{escape(model.name)} · catalog version {model.version}'
        f" · {escape(model.category)}</p>",
        _media(model, timecode),
        f"<p>{escape(model.description)}</p>",
        _facts(model),
        charts.markup(model.charts),
        _annotations(model),
        f'<p><a href="{links.category_path(model.name, model.category)}">'
        f"back to {escape(model.category)}</a></p>",
    ]
    return _document(f"{model.title} - {model.name}", body)


def failure(message):
    """The page an error response carries instead of a traceback."""
    return _document("mvault", [f'<p class="notice">{escape(message)}</p>'])


def _media(model, timecode):
    """What the vault holds of the entry itself, played or shown from its files.

    A vault that downloaded the media plays it, one that only got as far as
    the preview shows that, and one with neither says so and leaves the rest
    of the page as it is. A media fragment seeks playback to ``timecode``,
    which a vault holding no media has nothing to do with.
    """
    preview = links.preview_path(model.name, model.identifier) if model.preview else None
    if model.media_file is not None:
        poster = f' poster="{preview}"' if preview else ""
        start = f"#t={timecode}" if timecode is not None else ""
        source = links.media_path(model.name, model.media_file)
        return f'<video class="media" controls{poster} src="{source}{start}"></video>'
    if preview is not None:
        return f'<img class="media" src="{preview}" alt="preview of {escape(model.title)}">'
    return f'<p class="state">{NO_MEDIA}</p>'


def _annotations(model):
    """The notes kept on this entry, in the order they were created."""
    if not model.annotations:
        return f'<p class="state">{NO_ANNOTATIONS}</p>'
    return (
        "<h2>annotations</h2>"
        '<ol class="annotations">'
        + "".join(_annotation(found) for found in model.annotations)
        + "</ol>"
    )


def _annotation(found):
    """One note: the second it points at, what it is called, and what it says.

    The timecode is shown as the whole seconds it is stored as, which is also
    what the page is asked for to open the media there.
    """
    said = f'<p class="note">{escape(found["body"])}</p>' if found["body"] else ""
    return (
        f'<li class="annotation" data-annotation="{escape(found["id"])}">'
        f'<span class="timecode">{found["timecode"]}</span> '
        f'<span class="note-title">{escape(found["title"])}</span>{said}</li>'
    )


def _facts(model):
    """The entry's static metadata, closing on its page at the source platform."""
    return (
        '<dl class="facts">'
        f"<dt>published</dt><dd>{escape(str(model.published))}</dd>"
        f"<dt>dimensions</dt><dd>{model.width} × {model.height}</dd>"
        f'<dt>source</dt><dd><a href="{escape(model.source_url)}">'
        f"{escape(model.source_url)}</a></dd>"
        "</dl>"
    )


def _navigation(model):
    """Links to the categories this vault's version offers."""
    return "<nav>" + "".join(
        f'<a class="here">{escape(category)}</a>'
        if category == model.category
        else f'<a href="{links.category_path(model.name, category)}">{escape(category)}</a>'
        for category in model.categories
    ) + "</nav>"


def _entry(model, row):
    """One listed entry: its title as a link, followed by the states it is in."""
    states = [DOWNLOADED if row.downloaded else UNDOWNLOADED]
    if row.removed:
        states.append(REMOVED)
    labels = "".join(f'<span class="state">{state}</span>' for state in states)
    target = links.entry_path(model.name, model.category, row.identifier)
    return (
        f'<li class="{" ".join(["entry", *states])}" id="{escape(row.identifier)}">'
        f'<a href="{target}">{escape(row.title)}</a>{labels}</li>'
    )


def _document(title, body):
    """Wrap rendered body lines in the viewer's HTML document."""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )
