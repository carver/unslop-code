"""Turning a viewer request into the response it deserves.

Routing is kept apart from the HTTP plumbing: a route takes the pieces of a
request and returns a :class:`Response`, and never raises for a vault that is
missing, unreadable or asked for under the wrong category. A request for
something a vault does not hold is answered with a page saying so, under the
status that says the same.

``GET`` reads; ``POST``, ``PATCH`` and ``DELETE`` on an entry annotate it, and
send the browser back to the page that shows the result.
"""

from collections import namedtuple
from urllib.parse import parse_qs

from .. import annotations, links
from ..errors import VaultError
from . import annotate, assets, pages, vaults

CATALOG_FIELD = "catalog"
HTML_TYPE = "text/html; charset=utf-8"

OK_STATUS = 200
REDIRECT_STATUS = 303
BAD_REQUEST_STATUS = 400
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
        return _catalog(root, segments[1:], query)
    if segments[0] == links.VAULT_SEGMENT:
        return _asset(root, segments[1:])
    return _redirect(links.ROOT)


def post(root, segments, body):
    """Answer ``POST``: the vault form at the root, a new annotation on an entry."""
    if not segments:
        name = _field(parse_qs(body.decode("utf-8", errors="replace")), CATALOG_FIELD)
        return _redirect(links.catalog_path(name) if name else links.ROOT)
    return _annotate(root, segments, body, annotations.create, seek=True)


def patch(root, segments, body):
    """Answer ``PATCH``: the new title or body of one annotation of an entry."""
    return _annotate(root, segments, body, annotations.update)


def delete(root, segments, body):
    """Answer ``DELETE``: one annotation an entry is to keep no longer."""
    return _annotate(root, segments, body, annotations.delete)


def failure():
    """The response a request that could not be routed at all is answered with."""
    return _error(ERROR_STATUS, FAILURE_MESSAGE)


def _catalog(root, rest, query):
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
    return _entry(root, name, view, rest[1], rest[2], query)


def _entry(root, name, view, category, identifier, query):
    """Answer the detail page of one entry of one category of one vault."""
    found = vaults.detail(root, name, view, category, identifier)
    if found is None:
        return _error(NOT_FOUND_STATUS, NO_ENTRY_MESSAGE)
    timecode = annotations.read_timecode(_field(query, links.TIMECODE_FIELD))
    return _page(pages.detail(found, timecode), visited=name)


def _annotate(root, segments, body, change, seek=False):
    """Apply one annotation change to an entry and send the browser back to it.

    A legacy vault is migrated on the way, so the entry can end up in another
    category than the one it was asked for under, and the redirect names the
    one it resides in now. A create seeks the page to the second it pinned; an
    update or a delete leaves the page to open where it would anyway.
    """
    if len(segments) != 4 or segments[0] != links.CATALOG_SEGMENT:
        return _redirect(links.ROOT)
    _, name, requested, identifier = segments
    vault = vaults.path(root, name)
    if vault is None:
        return _redirect(links.missing_path(name))
    try:
        applied = annotate.apply(vault, requested, identifier, body, change)
    except annotations.NotFound as error:
        return _error(NOT_FOUND_STATUS, str(error))
    except annotations.AnnotationError as error:
        return _error(BAD_REQUEST_STATUS, str(error))
    except VaultError as error:
        return _error(ERROR_STATUS, str(error))
    if seek:
        seconds = applied.annotation[annotations.TIMECODE_FIELD]
        return _redirect(links.entry_timecode_path(name, applied.category, identifier, seconds))
    return _redirect(links.entry_path(name, applied.category, identifier))


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
