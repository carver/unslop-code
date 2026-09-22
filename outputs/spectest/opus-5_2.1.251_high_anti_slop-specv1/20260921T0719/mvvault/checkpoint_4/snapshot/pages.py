"""The HTML the viewer serves: a landing page and one category listing.

Pages are rendered from a catalog view and the media files a vault holds;
nothing here reads the disk or decides what a request means.
"""

from dataclasses import dataclass
from html import escape
from typing import Sequence

import downloads
import viewer
from catalogs import Entry
from views import CatalogGroup, CatalogView

#: The states a listed entry can be in, shown as badges and as CSS classes.
DOWNLOADED = "downloaded"
UNDOWNLOADED = "undownloaded"
REMOVED = "removed"

STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 48rem; }
nav a { margin-right: 1rem; }
nav a.current { font-weight: bold; text-decoration: none; }
ol.entries { list-style: decimal; padding-left: 2rem; }
li.entry { margin: 0.25rem 0; padding: 0.25rem; }
li.undownloaded a { color: #777; font-style: italic; }
li.removed a { text-decoration: line-through; }
li.selected { background: #fdf3c0; outline: 2px solid #e0b400; }
span.badge { border-radius: 0.6rem; font-size: 0.75rem; padding: 0.1rem 0.5rem; }
span.downloaded { background: #d8f0d8; }
span.undownloaded { background: #eee; }
span.removed { background: #f3d6d6; }
p.missing { color: #a00; }
"""


@dataclass(frozen=True)
class Row:
    """One entry as the listing shows it."""

    identifier: str
    title: str
    states: tuple[str, ...]
    selected: bool


def landing(recent: Sequence[tuple[str, str]], missing: str) -> str:
    """The page asking for a vault, and offering the ones already visited.

    ``missing`` names the vault a request asked for in vain, if any.
    """
    notice = f"<p class='missing'>No vault named '{escape(missing)}' here.</p>" if missing else ""
    return _document(
        "mvault viewer",
        f"<h1>mvault viewer</h1>{notice}"
        "<form method='post' action='/'>"
        "<label for='catalog'>Vault name</label> "
        "<input id='catalog' name='catalog' autofocus>"
        "<button type='submit'>Open</button>"
        "</form>"
        f"{_recent_list(recent)}",
    )


def listing(
    name: str, view: CatalogView, group: CatalogGroup, held: Sequence[str], selected: str
) -> str:
    """The entries of one category, in catalog order.

    ``selected`` names the entry a viewer link pointed at, which is marked out
    among the others.
    """
    rows = _rows(view, group, held, selected)
    items = "".join(_entry_item(name, group.category, row) for row in rows)
    return _document(
        f"{name} / {group.category}",
        f"<h1><a href='/'>mvault</a> / {escape(name)}</h1>"
        f"<p>Catalog version {view.version}, {len(group.entries)} {escape(group.category)}</p>"
        f"{_navigation(name, view, group.category)}"
        f"<ol class='entries'>{items}</ol>",
    )


def failure(message: str) -> str:
    """The page shown instead of a request the viewer does not answer."""
    return _document(
        "mvault viewer",
        f"<h1>{escape(message)}</h1><p><a href='/'>Back to the vault list</a>.</p>",
    )


def _rows(
    view: CatalogView, group: CatalogGroup, held: Sequence[str], selected: str
) -> list[Row]:
    """Describe every entry of a category as the listing needs it.

    An entry whose catalog version never tracked a title is listed under its
    identifier instead.
    """
    return [
        Row(
            identifier=entry["id"],
            title=view.current(entry, "title") or entry["id"],
            states=_states(view, entry, held),
            selected=entry["id"] == selected,
        )
        for entry in group.entries
    ]


def _states(view: CatalogView, entry: Entry, held: Sequence[str]) -> tuple[str, ...]:
    """Whether an entry is downloaded, and whether it is gone from the source.

    Only version 3 records removals, so entries of older vaults are never
    marked as removed.
    """
    downloaded = DOWNLOADED if downloads.is_held(entry["id"], held) else UNDOWNLOADED
    return (downloaded, REMOVED) if view.current(entry, "removed") else (downloaded,)


def _entry_item(name: str, category: str, row: Row) -> str:
    """One list item: a link to the entry, followed by the states it is in."""
    classes = " ".join(["entry", *row.states, *(["selected"] if row.selected else [])])
    badges = "".join(f"<span class='badge {state}'>{state}</span> " for state in row.states)
    link = viewer.catalog_path(name, category, row.identifier)
    return (
        f"<li class='{classes}' id='{escape(row.identifier)}'>"
        f"<a href='{escape(link)}'>{escape(row.title)}</a> {badges}</li>"
    )


def _navigation(name: str, view: CatalogView, current: str) -> str:
    """Links to every category the vault version addresses, this one marked."""
    links = []
    for category in view.categories:
        marker = " class='current'" if category == current else ""
        path = escape(viewer.catalog_path(name, category))
        links.append(f"<a{marker} href='{path}'>{escape(category)}</a>")
    return f"<nav>{''.join(links)}</nav>"


def _recent_list(recent: Sequence[tuple[str, str]]) -> str:
    """The vaults visited before, newest first, each on its opening page."""
    if not recent:
        return ""
    items = "".join(
        f"<li><a href='{escape(path)}'>{escape(name)}</a></li>" for name, path in recent
    )
    return f"<h2>Recent vaults</h2><ul class='recent'>{items}</ul>"


def _document(title: str, body: str) -> str:
    """Wrap rendered body markup in the page every viewer response shares."""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title><style>{STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )
