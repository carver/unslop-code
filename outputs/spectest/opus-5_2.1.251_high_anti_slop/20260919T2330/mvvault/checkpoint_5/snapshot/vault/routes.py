"""Routing of the viewer requests, from a request path to a :class:`Response`.

The routes never raise on a request that names something the viewer cannot
serve: an unknown vault goes back to the landing page with a notice, an unknown
category goes to the vault's default category page, and a missing entry or file
gets a rendered error page rather than a traceback.
"""

from http import HTTPStatus
from typing import NamedTuple
from urllib.parse import parse_qs, unquote, urlencode

from . import assets, detail, pages, viewer

HOME = "/"
CATALOG_ROOT = "catalog"
#: Form field of the landing page naming the vault to open.
FORM_FIELD = "catalog"
#: Query parameter the landing page reads to report a vault it could not open.
MISSING_PARAM = "missing"
HTML_TYPE = "text/html; charset=utf-8"


class Response(NamedTuple):
    """One HTTP answer: its status, its headers and its encoded body."""

    status: int
    headers: tuple
    body: bytes


def get_page(target, store):
    """Answer a GET for ``target``, the request path together with its query string."""
    path, _, query = target.partition("?")
    segments = [unquote(segment) for segment in path.split("/") if segment]
    if not segments:
        return _html(pages.landing(_recent_links(store), _missing(query)))
    if segments[0] == CATALOG_ROOT and len(segments) <= 4:
        return _catalog(segments[1:], store)
    if segments[0] == viewer.VAULT_ROOT and len(segments) == 4:
        return _asset(path, *segments[1:])
    return _html(pages.not_found(path), HTTPStatus.NOT_FOUND)


def post_form(path, body):
    """Answer a POST of a form-encoded ``body``: open the named vault, or go back home."""
    if path != HOME:
        return _html(pages.not_found(path), HTTPStatus.NOT_FOUND)
    name = parse_qs(body).get(FORM_FIELD, [""])[0].strip()
    return _redirect(viewer.vault_path(name) if name else HOME)


def _catalog(segments, store):
    """Answer a ``/catalog`` route: the listing pages and the redirects that reach them."""
    if not segments:
        return _redirect(HOME)
    name = segments[0]
    loaded = viewer.load_view(name)
    if loaded is None:
        return _missing_vault(name)
    store.record(name)
    category = segments[1] if len(segments) > 1 else None
    entries = viewer.category_entries(loaded, category)
    if entries is None:
        return _redirect(viewer.category_path(name, viewer.default_category(loaded.version)))
    if len(segments) > 2:
        return _detail(name, loaded, category, entries, segments[2])
    rows = viewer.listing_rows(name, loaded, entries)
    return _html(pages.listing(name, category, rows, viewer.categories_for(loaded.version)))


def _detail(name, loaded, category, entries, entry_id):
    """Answer an entry route: the page of the entry this category holds under that id."""
    entry = detail.find_entry(entries, entry_id)
    if entry is None:
        page = pages.not_found(viewer.entry_path(name, category, entry_id))
        return _html(page, HTTPStatus.NOT_FOUND)
    return _html(pages.detail(name, category, detail.build(name, loaded, entry)))


def _asset(path, name, kind, target):
    """Answer a static route with a file the vault downloaded, and nothing else."""
    if not (viewer.is_contained(name) and viewer.is_contained(target)):
        return _html(pages.forbidden(path), HTTPStatus.FORBIDDEN)
    if viewer.load_view(name) is None:
        return _missing_vault(name)
    stored = assets.locate(name, kind, target)
    if stored is None:
        return _html(pages.not_found(path), HTTPStatus.NOT_FOUND)
    return Response(
        HTTPStatus.OK,
        (("Content-Type", assets.content_type(stored)),),
        stored.read_bytes(),
    )


def _missing_vault(name):
    """Send the browser back to the landing page, naming the vault it could not open."""
    return _redirect(f"{HOME}?{urlencode({MISSING_PARAM: name})}")


def _recent_links(store):
    """Pair each still-readable recent vault with its resolved default category page."""
    resolved = ((name, viewer.default_path(name)) for name in store.names())
    return [(name, path) for name, path in resolved if path]


def _missing(query):
    """Name of the vault a redirect could not open, when the query string carries one."""
    return parse_qs(query).get(MISSING_PARAM, [""])[0]


def _html(markup, status=HTTPStatus.OK):
    """Answer with a rendered page."""
    return Response(status, (("Content-Type", HTML_TYPE),), markup.encode("utf-8"))


def _redirect(location):
    """Answer with a redirect the browser follows as a GET."""
    return Response(HTTPStatus.SEE_OTHER, (("Location", location),), b"")
