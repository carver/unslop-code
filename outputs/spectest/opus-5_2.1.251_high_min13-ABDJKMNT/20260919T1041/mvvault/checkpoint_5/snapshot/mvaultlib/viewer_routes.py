"""Turning one viewer request into the response the spec asks for."""

from dataclasses import dataclass, field
from urllib.parse import quote, unquote

from . import recent, vault_view, viewer_assets, viewer_links, viewer_pages
from .errors import MvaultError

HTML_TYPE = "text/html; charset=utf-8"

#: Carries the name of a vault that was not found across the bounce to `/`.
MISSING_COOKIE = "mvault_missing"
MISSING_MAX_AGE = 30

OK, FOUND, SEE_OTHER, NOT_FOUND = 200, 302, 303, 404

#: How each kind of `/vault/<name>/<kind>/<leaf>` request finds its file.
ASSET_LOOKUPS = {
    viewer_links.MEDIA_SEGMENT: viewer_assets.stored_media,
    viewer_links.PREVIEW_SEGMENT: viewer_assets.stored_preview,
}


@dataclass(frozen=True)
class Request:
    """What a handler needs to know about an incoming request."""

    path: str
    query: dict = field(default_factory=dict)
    form: dict = field(default_factory=dict)
    cookies: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    """A status, headers and a body, ready to be written to the socket."""

    status: int
    body: bytes = b""
    headers: tuple = ()


def get(request):
    """`GET`: the landing page, a catalog route, a stored file, or a not-found page."""
    segments = _segments(request.path)
    if not segments:
        return _landing(request)
    if segments[0] == viewer_links.CATALOG_SEGMENT and 2 <= len(segments) <= 4:
        return _catalog(segments[1], segments[2:])
    if segments[0] == viewer_links.VAULT_SEGMENT and len(segments) == 4:
        return _asset(segments[1], segments[2], segments[3])
    return error_page(NOT_FOUND, "No such page.")


def post(request):
    """`POST /`: open the submitted vault, or return to the landing page."""
    if _segments(request.path):
        return error_page(NOT_FOUND, "No such page.")
    name = request.form.get("catalog", [""])[0].strip()
    return _redirect(viewer_links.catalog_route(name) if name else "/", SEE_OTHER)


def error_page(status, message):
    """A well-formed error response that says nothing about internals."""
    return _html(viewer_pages.error(message), status)


def _catalog(name, rest):
    """`/catalog/<name>[/<category>[/<id>]]`, read at the vault's own version."""
    view = _view(name)
    if view is None:
        return _vault_not_found(name)

    recent.record(name)
    if not rest or view.entries_of(rest[0]) is None:
        return _redirect(viewer_links.catalog_route(name, view.default_category), FOUND)
    if len(rest) > 1:
        return _entry(name, view, rest[0], rest[1])
    return _html(viewer_pages.listing(name, view, rest[0]))


def _entry(name, view, category, entry_id):
    """The detail page of one entry of `category`, which is the only place looked in."""
    entry = view.entry_in(category, entry_id)
    if entry is None:
        return error_page(NOT_FOUND, "No such entry in this category.")
    return _html(viewer_pages.detail(name, view, category, entry))


def _asset(name, kind, leaf):
    """`/vault/<name>/media/<file>` and `/vault/<name>/preview/<id>`."""
    if _view(name) is None:
        return _vault_not_found(name)
    if kind not in ASSET_LOOKUPS:
        return error_page(NOT_FOUND, "No such page.")

    found = ASSET_LOOKUPS[kind](name, leaf)
    if found is None:
        return error_page(NOT_FOUND, "No such file.")
    body, content_type = found
    return Response(OK, body, (("Content-Type", content_type),))


def _landing(request):
    """The landing page, plus the notice left behind by a missing vault."""
    missing = request.query.get("missing", [None])[0] or request.cookies.get(MISSING_COOKIE)
    headers = ((("Set-Cookie", f"{MISSING_COOKIE}=; Path=/; Max-Age=0"),) if missing else ())
    page = viewer_pages.landing(_recent_vaults(), unquote(missing) if missing else None)
    return _html(page, headers=headers)


def _vault_not_found(name):
    """Bounce to the landing page, telling it which vault could not be read."""
    cookie = f"{MISSING_COOKIE}={quote(name)}; Path=/; Max-Age={MISSING_MAX_AGE}"
    return _redirect("/", FOUND, (("Set-Cookie", cookie),))


def _recent_vaults():
    """Recently visited vaults, each with the route its default category lives at."""
    return [(name, default_route(name)) for name in recent.names()]


def default_route(name):
    """Where a bare reference to `name` leads once its version is resolved."""
    view = _view(name)
    if view is None:
        return viewer_links.catalog_route(name)
    return viewer_links.catalog_route(name, view.default_category)


def _view(name):
    """The vault's view, or `None` when it cannot be read as a vault at all."""
    if not _is_vault_name(name):
        return None
    try:
        return vault_view.load_view(name)
    except MvaultError:
        return None


def _is_vault_name(name):
    """A vault name addresses a single directory beside the served vaults."""
    return name not in ("", ".", "..") and "/" not in name and "\\" not in name


def _segments(path):
    """The decoded, non-empty path segments of a request path."""
    return [unquote(segment) for segment in path.split("/") if segment]


def _html(page, status=OK, headers=()):
    return Response(status, page.encode("utf-8"), (("Content-Type", HTML_TYPE), *headers))


def _redirect(location, status, headers=()):
    return Response(status, headers=(("Location", location), *headers))
