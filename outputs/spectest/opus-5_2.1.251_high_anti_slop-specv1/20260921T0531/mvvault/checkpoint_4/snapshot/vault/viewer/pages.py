"""The HTML the viewer serves.

Pages are plain server-rendered documents: every state an entry can be in is
both a word in the listing and a class on its row, so it reads the same to a
person and to a stylesheet.
"""

from html import escape

from .. import links

DOWNLOADED = "downloaded"
UNDOWNLOADED = "missing"
REMOVED = "removed"

STYLE = """
body { font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 48rem; }
a { color: #1c5eb8; }
.meta { color: #666; }
.notice { background: #fdf0d5; border-left: 4px solid #c2762a; padding: .5rem .75rem; }
nav a { margin-right: 1rem; }
nav .here { font-weight: 700; text-decoration: none; color: #111; }
ul.entries { list-style: none; padding: 0; }
.entry { border-bottom: 1px solid #eee; display: flex; gap: .75rem; padding: .4rem 0; }
.entry .state { color: #666; font-size: .8rem; text-transform: uppercase; }
.entry.missing a { color: #767676; }
.entry.removed a { text-decoration: line-through; }
.entry.current { background: #fff6bf; }
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


def listing(model, highlighted):
    """One category listing, with the entry ``highlighted`` surfaced if given."""
    body = [
        f"<h1>{escape(model.name)}</h1>",
        f'<p class="meta">catalog version {model.version}</p>',
        _navigation(model),
        '<ul class="entries">',
        *(_entry(model, row, highlighted) for row in model.rows),
        "</ul>",
        f'<p><a href="{links.ROOT}">all vaults</a></p>',
    ]
    return _document(f"{model.name} - {model.category}", body)


def failure(message):
    """The page an error response carries instead of a traceback."""
    return _document("mvault", [f'<p class="notice">{escape(message)}</p>'])


def _navigation(model):
    """Links to the categories this vault's version offers."""
    return "<nav>" + "".join(
        f'<a class="here">{escape(category)}</a>'
        if category == model.category
        else f'<a href="{links.category_path(model.name, category)}">{escape(category)}</a>'
        for category in model.categories
    ) + "</nav>"


def _entry(model, row, highlighted):
    """One listed entry: its title as a link, followed by the states it is in."""
    states = [DOWNLOADED if row.downloaded else UNDOWNLOADED]
    if row.removed:
        states.append(REMOVED)
    classes = ["entry", *states] + (["current"] if row.identifier == highlighted else [])
    labels = "".join(f'<span class="state">{state}</span>' for state in states)
    target = links.entry_path(model.name, model.category, row.identifier)
    return (
        f'<li class="{" ".join(classes)}" id="{escape(row.identifier)}">'
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
