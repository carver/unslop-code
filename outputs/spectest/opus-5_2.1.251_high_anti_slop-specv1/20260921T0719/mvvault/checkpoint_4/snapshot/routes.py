"""What the viewer answers to a request, apart from how it is delivered.

Every route resolves against the directory the server was started in: a path
names a vault below it, the category the vault version groups entries in and,
at its longest, the entry a viewer link pointed at.
"""

from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import catalogs
import downloads
import pages
import recents
import viewer
import views
from errors import MvaultError
from views import CatalogView

#: Query the landing page reports an unreadable vault under.
MISSING_QUERY = "missing"

#: Longest path the viewer answers: ``/catalog/<name>/<category>/<id>``.
MAX_SEGMENTS = 4


@dataclass(frozen=True)
class Response:
    """What to send back: a status, a body and, for a redirect, a target."""

    status: HTTPStatus
    body: str = ""
    location: str = ""


#: Answers to a path the viewer serves nothing at, and to a request it broke on.
NOT_FOUND = Response(HTTPStatus.NOT_FOUND, pages.failure("No such page"))
FAILURE = Response(
    HTTPStatus.INTERNAL_SERVER_ERROR, pages.failure("The viewer could not answer that request")
)


def get(directory: Path, target: str) -> Response:
    """Answer a GET of ``target``: the landing page, or a catalog route."""
    url = urlsplit(target)
    segments = [unquote(part) for part in url.path.split("/") if part]
    if not segments:
        return _landing(directory, parse_qs(url.query))
    if segments[0] != viewer.CATALOG_ROOT or len(segments) > MAX_SEGMENTS:
        return NOT_FOUND
    return _catalog(directory, segments[1:])


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
        return _redirect(f"/?{urlencode({MISSING_QUERY: name})}")
    recents.visit(directory, name)
    group = view.group(segments[1]) if len(segments) > 1 else None
    if group is None:
        return _redirect(_opening_path(name, view))
    held = downloads.held_media(directory / name)
    selected = segments[2] if len(segments) > 2 else ""
    return Response(HTTPStatus.OK, pages.listing(name, view, group, held, selected))


def _landing(directory: Path, query: dict[str, list[str]]) -> Response:
    """The landing page, listing the vaults this directory was browsed for."""
    recent = [
        (name, _opening_path(name, view))
        for name in recents.read(directory)
        if (view := _view(directory, name)) is not None
    ]
    missing = query.get(MISSING_QUERY, [""])[0]
    return Response(HTTPStatus.OK, pages.landing(recent, missing))


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


def _redirect(location: str) -> Response:
    """Send the visitor on to ``location``."""
    return Response(HTTPStatus.SEE_OTHER, location=location)
