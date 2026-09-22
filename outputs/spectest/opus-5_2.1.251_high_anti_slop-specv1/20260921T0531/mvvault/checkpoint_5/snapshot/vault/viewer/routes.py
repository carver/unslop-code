"""Turning a viewer request into the response it deserves.

Routing is kept apart from the HTTP plumbing: a route takes the pieces of a
request and returns a :class:`Response`, and never raises for a vault that is
missing, unreadable or asked for under the wrong category. A request for
something a vault does not hold is answered with a page saying so, under the
status that says the same.
"""

from collections import namedtuple

from .. import links
from . import assets, pages, vaults

CATALOG_FIELD = "catalog"
HTML_TYPE = "text/html; charset=utf-8"

OK_STATUS = 200
REDIRECT_STATUS = 303
FORBIDDEN_STATUS = 403
NOT_FOUND_STATUS = 404
ERROR_STATUS = 500

FAILURE_MESSAGE = "The viewer could not answer that request."
NO_ENTRY_MESSAGE = "This category holds no entry with that id."
NO_FILE_MESSAGE = "This vault stores no such file."
FORBIDDEN_MESSAGE = "That is not a file name this vault can be asked for."

#: One answer to a request: the body to send and the type it is, or a
#: redirect, plus the vault the request navigated to, which the browser's
#: recent list is to remember.
Response = namedtuple("Response", "status body content_type location visited")


def get(root, segments, query, recent):
    """Answer ``GET`` for the unquoted path ``segments`` below the viewer root."""
    if not segments:
        missing = _field(query, links.MISSING_FIELD)
        return _page(pages.landing(_recent_links(root, recent), missing))
    if segments[0] == links.CATALOG_SEGMENT:
        return _catalog(root, segments[1:])
    if segments[0] == links.VAULT_SEGMENT:
        return _asset(root, segments[1:])
    return _redirect(links.ROOT)


def post(fields):
    """Answer ``POST /`` for the parsed fields of a form-encoded body."""
    name = _field(fields, CATALOG_FIELD)
    return _redirect(links.catalog_path(name) if name else links.ROOT)


def failure():
    """The response a request that could not be routed at all is answered with."""
    return _error(ERROR_STATUS, FAILURE_MESSAGE)


def _catalog(root, rest):
    """Answer the ``/catalog`` routes: a vault, one of its categories, an entry."""
    if not rest or len(rest) > 3:
        return _redirect(links.ROOT)
    name = rest[0]
    view = vaults.read(root, name)
    if view is None:
        return _redirect(links.missing_path(name))
    if len(rest) == 1 or rest[1] not in vaults.categories(view):
        return _redirect(links.category_path(name, vaults.default_category(view)), visited=name)
    if len(rest) == 2:
        return _page(pages.listing(vaults.listing(root, name, view, rest[1])), visited=name)
    return _entry(root, name, view, rest[1], rest[2])


def _entry(root, name, view, category, identifier):
    """Answer the detail page of one entry of one category of one vault."""
    found = vaults.detail(root, name, view, category, identifier)
    if found is None:
        return _error(NOT_FOUND_STATUS, NO_ENTRY_MESSAGE)
    return _page(pages.detail(found), visited=name)


def _asset(root, rest):
    """Answer the ``/vault`` routes: one stored media file, one preview image."""
    if len(rest) != 3 or rest[1] not in links.ASSET_KINDS:
        return _redirect(links.ROOT)
    name, kind, requested = rest
    if vaults.read(root, name) is None:
        return _redirect(links.missing_path(name))
    if not assets.names_one_file(requested):
        return _error(FORBIDDEN_STATUS, FORBIDDEN_MESSAGE)
    found = assets.locate(root, name, kind, requested)
    if found is None:
        return _error(NOT_FOUND_STATUS, NO_FILE_MESSAGE)
    return Response(OK_STATUS, found.path.read_bytes(), found.content_type, None, None)


def _recent_links(root, recent):
    """Each remembered vault that is still there, with its default category page."""
    seen = ((name, vaults.read(root, name)) for name in recent)
    return [
        (name, links.category_path(name, vaults.default_category(view)))
        for name, view in seen
        if view is not None
    ]


def _field(fields, name):
    """First value parsed for the field ``name``, or ``None`` if it has none."""
    return fields.get(name, [None])[0]


def _page(html, visited=None):
    return Response(OK_STATUS, html.encode("utf-8"), HTML_TYPE, None, visited)


def _redirect(location, visited=None):
    return Response(REDIRECT_STATUS, b"", HTML_TYPE, location, visited)


def _error(status, message):
    return Response(status, pages.failure(message).encode("utf-8"), HTML_TYPE, None, None)
