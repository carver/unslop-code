"""Turning a viewer request into the response it deserves.

Routing is kept apart from the HTTP plumbing: a route takes the pieces of a
request and returns a :class:`Response`, and never raises for a vault that is
missing, unreadable or asked for under the wrong category.
"""

from collections import namedtuple

from .. import links
from . import pages, vaults

CATALOG_SEGMENT = "catalog"
CATALOG_FIELD = "catalog"
OK_STATUS = 200
REDIRECT_STATUS = 303
ERROR_STATUS = 500
FAILURE_MESSAGE = "The viewer could not answer that request."

#: One answer to a request: an HTML body or a redirect, plus the vault the
#: request navigated to, which the browser's recent list is to remember.
Response = namedtuple("Response", "status html location visited")


def get(root, segments, query, recent):
    """Answer ``GET`` for the unquoted path ``segments`` below the viewer root."""
    if not segments:
        missing = _field(query, links.MISSING_FIELD)
        return _page(pages.landing(_recent_links(root, recent), missing))
    if segments[0] != CATALOG_SEGMENT or len(segments) > 4:
        return _redirect(links.ROOT)
    return _catalog(root, segments[1:])


def post(fields):
    """Answer ``POST /`` for the parsed fields of a form-encoded body."""
    name = _field(fields, CATALOG_FIELD)
    return _redirect(links.catalog_path(name) if name else links.ROOT)


def failure():
    """The response a request that could not be routed at all is answered with."""
    return Response(ERROR_STATUS, pages.failure(FAILURE_MESSAGE), None, None)


def _catalog(root, rest):
    """Answer the ``/catalog`` routes: a vault, one of its categories, an entry."""
    if not rest:
        return _redirect(links.ROOT)
    name = rest[0]
    view = vaults.read(root, name)
    if view is None:
        return _redirect(links.missing_path(name))
    default = links.category_path(name, vaults.default_category(view))
    if len(rest) == 1 or rest[1] not in vaults.categories(view):
        return _redirect(default, visited=name)
    listing = vaults.listing(root, name, view, rest[1])
    highlighted = rest[2] if len(rest) > 2 else None
    return _page(pages.listing(listing, highlighted), visited=name)


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
    return Response(OK_STATUS, html, None, visited)


def _redirect(location, visited=None):
    return Response(REDIRECT_STATUS, "", location, visited)
