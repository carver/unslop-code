"""HTML rendering of the viewer pages.

Every page is a self-contained document: the styles that tell the entry states
apart travel with it, so the server never has to serve assets of its own.
"""

from html import escape

from . import viewer

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
li.selected { outline: 2px solid #14568c; }
.state, .flag { font-size: .8rem; margin-left: .6rem; text-transform: uppercase; }
.state { color: #4a4a4a; }
.flag { color: #a11; }
.missing { background: #fdf0f0; border-left: 4px solid #a11; padding: .6rem .8rem; }
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


def listing(name, category, rows, categories, highlight):
    """A category listing: every entry with its state and a link to its own page."""
    heading = f"{escape(name)} / {escape(category)}"
    body = [
        f'<h1><a href="/">mvault</a> / {heading}</h1>',
        _navigation(name, category, categories),
        f'<ul class="entries">{"".join(_row(name, category, row, highlight) for row in rows)}</ul>',
    ]
    return _document(f"{name} - {category}", body)


def not_found(path):
    """The page answering a request for a route the viewer does not serve."""
    body = [
        "<h1>Not found</h1>",
        f"<p>The viewer serves no page at {escape(path)}.</p>",
        '<p><a href="/">Back to the vault list</a></p>',
    ]
    return _document("Not found", body)


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


def _row(name, category, row, highlight):
    """Render one entry: its title link, its download state and its removal flag."""
    classes = ["entry", "downloaded" if row.downloaded else "pending"]
    if row.removed:
        classes.append("removed")
    if row.id == highlight:
        classes.append("selected")
    href = escape(viewer.entry_path(name, category, row.id), quote=True)
    flag = '<span class="flag">removed</span>' if row.removed else ""
    return (
        f'<li class="{" ".join(classes)}" id="entry-{escape(row.id, quote=True)}">'
        f'<a href="{href}">{escape(row.title)}</a>'
        f'<span class="state">{"downloaded" if row.downloaded else "not downloaded"}</span>'
        f"{flag}</li>"
    )
