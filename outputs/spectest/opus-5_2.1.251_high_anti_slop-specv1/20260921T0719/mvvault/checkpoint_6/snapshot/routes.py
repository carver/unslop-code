"""What the viewer answers to a request, apart from how it is delivered.

Every route resolves against the directory the server was started in: a path
names a vault below it and then either a page about its catalog -- a category,
or one entry of it -- or one of the files it downloaded.  An entry is the one
thing a visitor can also write to: the methods besides ``GET`` on its page
change the annotations it carries, which :mod:`editing` applies to the vault.
"""

from http import HTTPStatus
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

import annotations
import assets
import catalogs
import downloads
import editing
import pages
import recents
import responses
import viewer
import views
from assets import Asset
from errors import MvaultError
from responses import Response
from views import CatalogGroup, CatalogView

#: Segments a catalog route may name below ``/catalog``, and a file route
#: below ``/vault``: ``<name>/<category>/<id>`` and ``<name>/<kind>/<target>``.
CATALOG_SEGMENTS = 3
FILE_SEGMENTS = 3

#: Where each kind of stored file a ``/vault`` path can name is looked up.
FILE_KINDS: dict[str, Callable[[Path, str], Optional[Asset]]] = {
    viewer.MEDIA_ROUTE: assets.media,
    viewer.PREVIEW_ROUTE: assets.preview,
}


def get(directory: Path, target: str) -> Response:
    """Answer a GET of ``target``: a page, a stored file or the landing page."""
    segments = _segments(target)
    if not segments:
        return _landing(directory, parse_qs(urlsplit(target).query))
    root, rest = segments[0], segments[1:]
    if root == viewer.CATALOG_ROOT and len(rest) <= CATALOG_SEGMENTS:
        return _catalog(directory, rest)
    if root == viewer.VAULT_ROOT and len(rest) == FILE_SEGMENTS:
        return _file(directory, *rest)
    return responses.NOT_FOUND


def post(directory: Path, target: str, body: str) -> Response:
    """Answer the landing page form, or add an annotation to an entry."""
    if _segments(target)[:1] == [viewer.CATALOG_ROOT]:
        return _annotate(directory, target, body, annotations.create)
    named = parse_qs(body).get("catalog")
    return responses.redirect(viewer.catalog_path(named[0].strip()) if named else "/")


def patch(directory: Path, target: str, body: str) -> Response:
    """Rewrite one annotation of the entry ``target`` names."""
    return _annotate(directory, target, body, annotations.update)


def delete(directory: Path, target: str, body: str) -> Response:
    """Drop one annotation of the entry ``target`` names."""
    return _annotate(directory, target, body, annotations.remove)


def start_path(directory: Path, name: Optional[str]) -> str:
    """Where a browser should be pointed when the viewer starts.

    Without a vault that is the landing page; with one it is the page that
    vault's catalog version opens on.
    """
    if name is None:
        return "/"
    view = _view(directory, name)
    return _opening_path(name, view) if view else viewer.catalog_path(name)


def _annotate(
    directory: Path, target: str, body: str, change: editing.Change
) -> Response:
    """Answer a request that changes the annotations of one entry.

    Only the page of an entry carries annotations, so a path naming anything
    else is answered the way any other unserved path is.
    """
    segments = _segments(target)
    if segments[:1] != [viewer.CATALOG_ROOT] or len(segments) != CATALOG_SEGMENTS + 1:
        return responses.NOT_FOUND
    return editing.annotate(directory, segments[1:], body, change)


def _catalog(directory: Path, segments: list[str]) -> Response:
    """Answer a ``/catalog`` route, recording the visit it stands for.

    A category the vault version does not know, or none at all, opens the
    vault on its default category instead.
    """
    if not segments:
        return responses.redirect("/")
    name = segments[0]
    view = _view(directory, name)
    if view is None:
        return responses.missing(name)
    recents.visit(directory, name)
    group = view.group(segments[1]) if len(segments) > 1 else None
    if group is None:
        return responses.redirect(_opening_path(name, view))
    if len(segments) > 2:
        return _entry(directory / name, name, view, group, segments[2])
    held = downloads.held_media(directory / name)
    return responses.page(HTTPStatus.OK, pages.listing(name, view, group, held))


def _entry(
    vault: Path, name: str, view: CatalogView, group: CatalogGroup, identifier: str
) -> Response:
    """The detail page of one entry of one category of a vault."""
    entry = group.entry(identifier)
    if entry is None:
        return responses.refusal(
            HTTPStatus.NOT_FOUND,
            f"No entry '{identifier}' among the {group.category} of '{name}'",
        )
    files = assets.entry_files(vault, identifier)
    return responses.page(HTTPStatus.OK, pages.detail(name, view, group, entry, files))


def _file(directory: Path, name: str, kind: str, target: str) -> Response:
    """Answer a ``/vault`` route with the stored file it names.

    A name reaching outside the directory its kind is stored in names no file
    there, so it is answered the way any other unknown file is.
    """
    if _view(directory, name) is None:
        return responses.missing(name)
    look_up = FILE_KINDS.get(kind)
    asset = look_up(directory / name, target) if look_up else None
    if asset is None:
        return responses.NOT_FOUND
    return Response(HTTPStatus.OK, asset.path.read_bytes(), asset.content_type)


def _landing(directory: Path, query: dict[str, list[str]]) -> Response:
    """The landing page, listing the vaults this directory was browsed for."""
    recent = [
        (name, _opening_path(name, view))
        for name in recents.read(directory)
        if (view := _view(directory, name)) is not None
    ]
    missing = query.get(responses.MISSING_QUERY, [""])[0]
    return responses.page(HTTPStatus.OK, pages.landing(recent, missing))


def _segments(target: str) -> list[str]:
    """The path a request names, as the decoded segments it is made of."""
    return [unquote(part) for part in urlsplit(target).path.split("/") if part]


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
