"""What the viewer answers to a request, apart from how it is delivered.

Every route resolves against the directory the server was started in: a path
names a vault below it and then either a page about its catalog -- a category,
or one entry of it -- or one of the files it downloaded.
"""

from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import assets
import catalogs
import downloads
import pages
import recents
import viewer
import views
from assets import Asset
from errors import MvaultError
from views import CatalogGroup, CatalogView

#: Query the landing page reports an unreadable vault under.
MISSING_QUERY = "missing"

#: Content type every page the viewer renders is served as.
HTML_TYPE = "text/html; charset=utf-8"

#: Segments a catalog route may name below ``/catalog``, and a file route
#: below ``/vault``: ``<name>/<category>/<id>`` and ``<name>/<kind>/<target>``.
CATALOG_SEGMENTS = 3
FILE_SEGMENTS = 3


@dataclass(frozen=True)
class Response:
    """What to send back: a status, a body and, for a redirect, a target."""

    status: HTTPStatus
    body: bytes = b""
    content_type: str = HTML_TYPE
    location: str = ""


def page(status: HTTPStatus, markup: str) -> Response:
    """A rendered page, ready to be sent."""
    return Response(status, markup.encode("utf-8"))


#: Answers to a path the viewer serves nothing at, and to a request it broke on.
NOT_FOUND = page(HTTPStatus.NOT_FOUND, pages.failure("No such page"))
FAILURE = page(
    HTTPStatus.INTERNAL_SERVER_ERROR,
    pages.failure("The viewer could not answer that request"),
)

#: Where each kind of stored file a ``/vault`` path can name is looked up.
FILE_KINDS: dict[str, Callable[[Path, str], Optional[Asset]]] = {
    viewer.MEDIA_ROUTE: assets.media,
    viewer.PREVIEW_ROUTE: assets.preview,
}


def get(directory: Path, target: str) -> Response:
    """Answer a GET of ``target``: a page, a stored file or the landing page."""
    url = urlsplit(target)
    segments = [unquote(part) for part in url.path.split("/") if part]
    if not segments:
        return _landing(directory, parse_qs(url.query))
    root, rest = segments[0], segments[1:]
    if root == viewer.CATALOG_ROOT and len(rest) <= CATALOG_SEGMENTS:
        return _catalog(directory, rest)
    if root == viewer.VAULT_ROOT and len(rest) == FILE_SEGMENTS:
        return _file(directory, *rest)
    return NOT_FOUND


def post(body: str) -> Response:
    """Answer the landing page form, which names the vault to open."""
    named = parse_qs(body).get("catalog")
    return _redirect(viewer.catalog_path(named[0].strip()) if named else "/")


def start_path(directory: Path, name: Optional[str]) -> str:
    """Where a browser should be pointed when the viewer starts.

    Without a vault that is the landing page; with one it is the page that
    vault's catalog version opens on.
    """
    if name is None:
        return "/"
    view = _view(directory, name)
    return _opening_path(name, view) if view else viewer.catalog_path(name)


def _catalog(directory: Path, segments: list[str]) -> Response:
    """Answer a ``/catalog`` route, recording the visit it stands for.

    A category the vault version does not know, or none at all, opens the
    vault on its default category instead.
    """
    if not segments:
        return _redirect("/")
    name = segments[0]
    view = _view(directory, name)
    if view is None:
        return _missing(name)
    recents.visit(directory, name)
    group = view.group(segments[1]) if len(segments) > 1 else None
    if group is None:
        return _redirect(_opening_path(name, view))
    if len(segments) > 2:
        return _entry(directory / name, name, view, group, segments[2])
    held = downloads.held_media(directory / name)
    return page(HTTPStatus.OK, pages.listing(name, view, group, held))


def _entry(
    vault: Path, name: str, view: CatalogView, group: CatalogGroup, identifier: str
) -> Response:
    """The detail page of one entry of one category of a vault."""
    entry = group.entry(identifier)
    if entry is None:
        return page(
            HTTPStatus.NOT_FOUND,
            pages.failure(f"No entry '{identifier}' among the {group.category} of '{name}'"),
        )
    files = assets.entry_files(vault, identifier)
    return page(HTTPStatus.OK, pages.detail(name, view, group, entry, files))


def _file(directory: Path, name: str, kind: str, target: str) -> Response:
    """Answer a ``/vault`` route with the stored file it names.

    A name reaching outside the directory its kind is stored in names no file
    there, so it is answered the way any other unknown file is.
    """
    if _view(directory, name) is None:
        return _missing(name)
    look_up = FILE_KINDS.get(kind)
    asset = look_up(directory / name, target) if look_up else None
    if asset is None:
        return NOT_FOUND
    return Response(HTTPStatus.OK, asset.path.read_bytes(), asset.content_type)


def _landing(directory: Path, query: dict[str, list[str]]) -> Response:
    """The landing page, listing the vaults this directory was browsed for."""
    recent = [
        (name, _opening_path(name, view))
        for name in recents.read(directory)
        if (view := _view(directory, name)) is not None
    ]
    missing = query.get(MISSING_QUERY, [""])[0]
    return page(HTTPStatus.OK, pages.landing(recent, missing))


def _view(directory: Path, name: str) -> Optional[CatalogView]:
    """Read a stored vault, or report that it cannot be browsed.

    A vault that is absent, unreadable or written in an unsupported version
    is one the viewer sends the visitor back to the landing page for.
    """
    try:
        return views.open_view(catalogs.read(directory / name, name), name)
    except MvaultError:
        return None


def _opening_path(name: str, view: CatalogView) -> str:
    """The category page a vault of this catalog version opens on."""
    return viewer.catalog_path(name, view.default_category)


def _missing(name: str) -> Response:
    """Send the visitor back to the landing page, naming the vault it wanted."""
    return _redirect(f"/?{urlencode({MISSING_QUERY: name})}")


def _redirect(location: str) -> Response:
    """Send the visitor on to ``location``."""
    return Response(HTTPStatus.SEE_OTHER, location=location)
