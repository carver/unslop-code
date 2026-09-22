"""The HTML pages the viewer serves."""

from html import escape

from ..views import CatalogView
from .links import LANDING_PATH, category_path, entry_path
from .listing import EntryRow

FORM_FIELD = "catalog"
MISSING_PARAM = "missing"

STYLE = """
body { max-width: 46rem; margin: 2rem auto; padding: 0 1rem; color: #1b1b1b;
       font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.5; }
a { color: #1a4f8a; }
.meta { color: #5b5b5b; font-size: .875rem; }
.notice { background: #fdecea; border-left: 4px solid #c0392b; padding: .5rem .75rem; }
form { margin: 1rem 0 2rem; }
input { padding: .35rem .5rem; font-size: 1rem; }
button { padding: .35rem .9rem; font-size: 1rem; }
nav { margin: 1rem 0; }
nav a, nav .current { margin-right: .9rem; }
nav .current { font-weight: 700; color: inherit; }
ul.entries, ul.recent { list-style: none; padding: 0; }
.entry { border-bottom: 1px solid #e4e4e4; padding: .5rem .25rem; }
.entry.undownloaded { opacity: .6; }
.entry.removed .title { text-decoration: line-through; }
.entry.highlighted { background: #fff6d4; border-left: 4px solid #d4a017; }
.badge { font-size: .7rem; letter-spacing: .05em; text-transform: uppercase; margin-left: .6rem; }
.badge.downloaded { color: #1c7c3e; }
.badge.undownloaded { color: #8a6d1a; }
.badge.removed { color: #c0392b; }
.badge.highlighted { color: #7a5c00; }
"""


def landing_page(recent: list[tuple[str, str]], missing: str | None = None) -> str:
    """The page at ``/``: the vault form, and where this browser has been.

    ``recent`` pairs each visited vault with the default category page it
    resolves to, newest first.
    """
    parts = ["<h1>mvault</h1>"]
    if missing:
        parts.append(f'<p class="notice">No vault named "{escape(missing)}" was found.</p>')
    parts.append(
        f'<form method="post" action="{LANDING_PATH}">'
        f'<label for="{FORM_FIELD}">Vault name</label> '
        f'<input id="{FORM_FIELD}" name="{FORM_FIELD}" autofocus> '
        "<button type=\"submit\">Open</button></form>"
    )
    parts.append(_recent_section(recent))
    return _document("mvault", parts)


def category_page(
    name: str,
    view: CatalogView,
    category: str,
    rows: list[EntryRow],
    highlighted: str | None = None,
) -> str:
    """The listing of one category, with one entry surfaced when a link named it."""
    return _document(
        f"{name} / {category}",
        [
            f"<h1>{escape(name)}</h1>",
            f'<p class="meta">catalog version {view.version} of {escape(view.source)}</p>',
            _category_nav(name, view.categories, category),
            _entry_list(name, category, rows, highlighted),
        ],
    )


def error_page(status: int, message: str) -> str:
    """The page behind an HTTP error, so no failure answers with a traceback."""
    return _document(
        f"mvault: {status}",
        [f"<h1>{status}</h1>", f"<p>{escape(message)}</p>", f'<p><a href="{LANDING_PATH}">Back</a></p>'],
    )


def _recent_section(recent: list[tuple[str, str]]) -> str:
    """List the vaults this browser has opened, most recently visited first."""
    if not recent:
        return ""
    items = "".join(
        f'<li><a href="{escape(path)}">{escape(name)}</a></li>' for name, path in recent
    )
    return f'<h2>Recent vaults</h2>\n<ul class="recent">{items}</ul>'


def _category_nav(name: str, categories: tuple[str, ...], current: str) -> str:
    """Link the categories this catalog version has, marking the one on screen."""
    links = [
        f'<span class="current">{escape(category)}</span>'
        if category == current
        else f'<a href="{escape(category_path(name, category))}">{escape(category)}</a>'
        for category in categories
    ]
    return f"<nav>{''.join(links)}</nav>"


def _entry_list(
    name: str, category: str, rows: list[EntryRow], highlighted: str | None
) -> str:
    if not rows:
        return f"<p>No {escape(category)} are stored in this vault.</p>"
    items = "\n".join(_entry_item(name, category, row, highlighted) for row in rows)
    return f'<ul class="entries">\n{items}\n</ul>'


def _entry_item(name: str, category: str, row: EntryRow, highlighted: str | None) -> str:
    """One entry: its title as a link, plus a badge per state it is in."""
    state, label = ("downloaded", "downloaded") if row.downloaded else ("undownloaded", "not downloaded")
    classes = ["entry", state]
    badges = [_badge(state, label)]
    if row.removed:
        classes.append("removed")
        badges.append(_badge("removed", "removed"))
    if row.entry_id == highlighted:
        classes.append("highlighted")
        badges.append(_badge("highlighted", "selected"))
    link = escape(entry_path(name, category, row.entry_id))
    return (
        f'<li class="{" ".join(classes)}" id="entry-{escape(row.entry_id)}">'
        f'<a class="title" href="{link}">{escape(row.title)}</a>'
        f'{"".join(badges)}</li>'
    )


def _badge(state: str, text: str) -> str:
    return f'<span class="badge {state}">{text}</span>'


def _document(title: str, body: list[str]) -> str:
    """Wrap page content in the shared document shell."""
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n"
        + "\n".join(part for part in body if part)
        + "\n</body>\n</html>\n"
    )
