"""The viewer's HTML shell: the landing page, a category listing, plain
messages, and the document every page — the entry detail page included — is
wrapped in.

Rendering takes catalog views and already-resolved routes, so nothing here
reads the filesystem; the server decides what to show and this module decides
how it looks.
"""

from html import escape

from .download import is_stored
from .viewer import categories_for, catalog_route, entry_route

STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 48rem; }
ul { list-style: none; padding: 0; }
li.entry { padding: .3rem .6rem; border-left: .35rem solid #2b7; }
li.entry.missing { border-left-color: #bbb; color: #555; }
li.entry.removed { text-decoration: line-through; border-left-color: #c44; }
.badge { font-size: .75rem; margin-left: .5rem; color: #444; }
.notice { background: #fdd; padding: .5rem .8rem; }
.metadata dt { font-size: .75rem; color: #555; }
.metadata dd { margin: 0 0 .6rem; }
.preview, .media { max-width: 100%; }
.chart { margin: 1.5rem 0; }
.chart h2 { font-size: .9rem; font-weight: 600; margin: 0; }
.chart figcaption { font-size: .75rem; color: #555; }
.plot { width: 100%; height: 6rem; overflow: visible; }
.seek { font-size: .8rem; color: #555; }
li.annotation { padding: .3rem .6rem; border-left: .35rem solid #77b; }
.timecode { font-variant-numeric: tabular-nums; color: #555; }
.annotation-body { margin: .2rem 0 0; }
"""

# The badge each entry state carries in a listing; a state without one, such as
# an entry's membership of the listing itself, is shown by styling alone.
BADGES = {"downloaded": "downloaded", "missing": "no media", "removed": "removed"}


def document(title, body):
    """One HTML page: the viewer's shared head, then `body`."""
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def landing_page(recent, missing=None):
    """The landing page: the vault form, a not-found notice, recent vaults."""
    notice = f"<p class=\"notice\">Vault '{escape(missing)}' not found.</p>" if missing else ""
    return document(
        "mvault viewer",
        "\n".join(
            part
            for part in ["<h1>mvault viewer</h1>", notice, vault_form(), recent_list(recent)]
            if part
        ),
    )


def vault_form():
    """The form that opens a vault by name."""
    return (
        '<form method="post" action="/">\n'
        '<label for="catalog">Vault name</label>\n'
        '<input id="catalog" name="catalog" autofocus>\n'
        '<button type="submit">Open</button>\n'
        "</form>"
    )


def recent_list(recent):
    """The recently visited vaults as links, or nothing when there are none."""
    if not recent:
        return ""
    links = "\n".join(
        f'<li><a href="{escape(route)}">{escape(name)}</a></li>' for name, route in recent
    )
    return f"<h2>Recent vaults</h2>\n<ul>\n{links}\n</ul>"


def category_page(name, view, category, stored):
    """One category's entries in catalog order, with their state and links."""
    rows = "\n".join(
        entry_row(name, view, category, entry, stored) for entry in view.entries(category)
    )
    heading = (
        f"<h1>{escape(name)}</h1>\n"
        f"<p>catalog version {view.version} &middot; {escape(category)}</p>\n"
        f"{category_nav(name, view, category)}"
    )
    return document(f"{name} / {category}", f"{heading}\n<ul>\n{rows}\n</ul>")


def category_nav(name, view, category):
    """Links to this version's other categories."""
    others = [other for other in categories_for(view.version) if other != category]
    links = " ".join(f'<a href="{catalog_route(name, other)}">{other}</a>' for other in others)
    return f"<nav>{links}</nav>" if links else ""


def entry_row(name, view, category, entry, stored):
    """One listed entry: its current title, its link, and its state."""
    entry_id = entry["id"]
    states = ["entry", "downloaded" if is_stored(entry_id, stored) else "missing"]
    if view.detects_removals and view.current(entry, "removed"):
        states.append("removed")

    link = escape(entry_route(name, category, entry_id))
    title = escape(view.current(entry, "title"))
    badges = "".join(
        f'<span class="badge">{BADGES[state]}</span>' for state in states if state in BADGES
    )
    return f'<li class="{" ".join(states)}"><a href="{link}">{title}</a>{badges}</li>'


def message_page(title, message):
    """A plain page for an outcome that has nothing to list."""
    return document(title, f"<h1>{escape(title)}</h1>\n<p>{escape(message)}</p>")
