"""The HTML the viewer serves: a landing page, category listings and details.

Pages are rendered from a catalog view and from what the vault was found to
hold; nothing here reads the disk or decides what a request means.
"""

from dataclasses import dataclass
from html import escape
from typing import Sequence

import charts
import downloads
import viewer
from assets import EntryFiles
from catalogs import Entry
from views import CatalogGroup, CatalogView

#: The states an entry can be in, shown as badges and as CSS classes.
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
span.badge { border-radius: 0.6rem; font-size: 0.75rem; padding: 0.1rem 0.5rem; }
span.downloaded { background: #d8f0d8; }
span.undownloaded { background: #eee; }
span.removed { background: #f3d6d6; }
p.missing { color: #a00; }
dl.metadata dt { color: #52514e; font-size: 0.85rem; }
dl.metadata dd { margin: 0 0 0.5rem 0; }
video.media, img.preview { max-width: 100%; }
""" + charts.STYLE


@dataclass(frozen=True)
class Row:
    """One entry as the listing shows it."""

    identifier: str
    title: str
    states: tuple[str, ...]


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


def listing(name: str, view: CatalogView, group: CatalogGroup, held: Sequence[str]) -> str:
    """The entries of one category, in catalog order."""
    rows = _rows(view, group, held)
    items = "".join(_entry_item(name, group.category, row) for row in rows)
    return _document(
        f"{name} / {group.category}",
        f"<h1><a href='/'>mvault</a> / {escape(name)}</h1>"
        f"<p>Catalog version {view.version}, {len(group.entries)} {escape(group.category)}</p>"
        f"{_navigation(name, view, group.category)}"
        f"<ol class='entries'>{items}</ol>",
    )


def detail(
    name: str, view: CatalogView, group: CatalogGroup, entry: Entry, files: EntryFiles
) -> str:
    """Everything the vault knows about one entry.

    The metadata and the charts stand on their own, so an entry whose media
    was never downloaded, or which the source has dropped, reads the same as
    any other one.
    """
    identifier = entry["id"]
    title = view.current(entry, "title") or identifier
    return _document(
        f"{name} / {group.category} / {title}",
        f"<h1><a href='/'>mvault</a> / {escape(name)}</h1>"
        f"<p>Catalog version {view.version}</p>"
        f"<nav><a href='{escape(viewer.catalog_path(name, group.category))}'>"
        f"Back to {escape(group.category)}</a></nav>"
        f"<h2>{escape(title)}</h2>{_badges(_states(view, entry, files.media is not None))}"
        f"{_player(name, identifier, files)}"
        f"{_metadata(view, entry)}"
        f"{charts.charts(view, entry)}",
    )


def failure(message: str) -> str:
    """The page shown instead of a request the viewer does not answer."""
    return _document(
        "mvault viewer",
        f"<h1>{escape(message)}</h1><p><a href='/'>Back to the vault list</a>.</p>",
    )


def _rows(view: CatalogView, group: CatalogGroup, held: Sequence[str]) -> list[Row]:
    """Describe every entry of a category as the listing needs it.

    An entry whose catalog version never tracked a title is listed under its
    identifier instead.
    """
    return [
        Row(
            identifier=entry["id"],
            title=view.current(entry, "title") or entry["id"],
            states=_states(view, entry, downloads.is_held(entry["id"], held)),
        )
        for entry in group.entries
    ]


def _states(view: CatalogView, entry: Entry, downloaded: bool) -> tuple[str, ...]:
    """Whether an entry is downloaded, and whether it is gone from the source.

    Only version 3 records removals, so entries of older vaults are never
    marked as removed.
    """
    held = DOWNLOADED if downloaded else UNDOWNLOADED
    return (held, REMOVED) if view.current(entry, "removed") else (held,)


def _badges(states: Sequence[str]) -> str:
    """The states an entry is in, as the badges every page shows them as."""
    return "".join(f"<span class='badge {state}'>{state}</span> " for state in states)


def _entry_item(name: str, category: str, row: Row) -> str:
    """One list item: a link to the entry, followed by the states it is in."""
    link = viewer.catalog_path(name, category, row.identifier)
    return (
        f"<li class='{' '.join(['entry', *row.states])}' id='{escape(row.identifier)}'>"
        f"<a href='{escape(link)}'>{escape(row.title)}</a> {_badges(row.states)}</li>"
    )


def _player(name: str, identifier: str, files: EntryFiles) -> str:
    """The media the vault downloaded for an entry, ready to play.

    A vault that holds no media for the entry shows its preview image alone,
    and one that holds neither shows nothing at all.
    """
    poster = (
        f" poster='{escape(viewer.vault_path(name, viewer.PREVIEW_ROUTE, identifier))}'"
        if files.preview
        else ""
    )
    if files.media:
        source = escape(viewer.vault_path(name, viewer.MEDIA_ROUTE, files.media))
        return f"<video class='media' controls{poster} src='{source}'></video>"
    if files.preview:
        image = escape(viewer.vault_path(name, viewer.PREVIEW_ROUTE, identifier))
        return f"<img class='preview' src='{image}' alt='Preview of {escape(identifier)}'>"
    return ""


def _metadata(view: CatalogView, entry: Entry) -> str:
    """The description, publication, dimensions and source of one entry."""
    described = {
        "Description": view.current(entry, "description") or "",
        "Published": entry["published"],
        "Dimensions": f"{entry['width']} x {entry['height']}",
    }
    definitions = "".join(
        f"<dt>{term}</dt><dd class='{term.lower()}'>{escape(value)}</dd>"
        for term, value in described.items()
    )
    source = view.entry_source(entry["id"])
    return (
        f"<dl class='metadata'>{definitions}"
        f"<dt>Source</dt>"
        f"<dd><a class='source' href='{escape(source)}'>{escape(source)}</a></dd></dl>"
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
