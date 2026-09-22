"""The `serve` command: a local HTTP viewer for vaults of any version.

The server holds one served directory and reads each vault in its own version's
layout on every request, so nothing it shows requires a migration first. Routes
answer in HTML, with a saved file, or with a redirect; a request that names a
vault the directory does not hold returns to the landing page carrying that
vault's name, and any other failure becomes a plain error page rather than a
traceback.
"""

import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import pages
from .annotations import annotate, annotation_request
from .assets import escapes, media_asset, preview_asset, stored_assets
from .detail import detail_page
from .download import MEDIA_DIR, PREVIEW_DIR, stored_names
from .errors import AnnotationError, MvaultError
from .recents import RecentFile, from_cookie, merge, promote, to_cookie
from .viewer import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    catalog_route,
    categories_for,
    default_route,
    entry_route,
)
from .views import load_view

NOT_FOUND_MESSAGE = "The viewer has no page at that address."
FAILURE_MESSAGE = "The viewer could not build that page."
NO_ENTRY_MESSAGE = "That category holds no entry with that id."
NO_FILE_MESSAGE = "This vault has no such saved file."
TRAVERSAL_MESSAGE = "A saved file is only served from inside its own directory."

HTML_TYPE = "text/html; charset=utf-8"

# The two `/vault` endpoints: the directory each serves, and how a request
# names the file it wants inside it.
ASSET_KINDS = {"media": (MEDIA_DIR, media_asset), "preview": (PREVIEW_DIR, preview_asset)}


def serve_viewer(name=None, host=DEFAULT_HOST, port=DEFAULT_PORT, root="."):
    """Serve the viewer for the vaults in `root` and open a browser on it."""
    try:
        server = ViewerServer((host, port), root)
    except OSError as exc:
        raise MvaultError(f"cannot serve on {host}:{port}: {exc}") from exc

    url = browser_url(server, host, name)
    print(f"mvault viewer serving on {url}", flush=True)
    webbrowser.open(url)

    with server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def browser_url(server, host, name):
    """The URL `serve` opens: the landing page, or a named vault's own page.

    The host is used as it was given on the command line, which is not always
    how the server sees the address it bound.
    """
    path = "/" if name is None else vault_route(server, name)
    return f"http://{host}:{server.server_port}{path}"


def vault_route(server, name):
    """A vault's resolved default category route, by the version it declares."""
    view = server.vault_view(name)
    return default_route(name, view.version) if view else catalog_route(name)


def segments(target):
    """The decoded path segments of a request target, without its query."""
    path = urlsplit(target).path
    return [unquote(segment) for segment in path.split("/") if segment]


def timecode_query(target):
    """The `?timecode=` a request target asks a detail page to seek to, if any."""
    requested = parse_qs(urlsplit(target).query).get("timecode")
    return requested[0] if requested else None


class ViewerServer(ThreadingHTTPServer):
    """A viewer bound to one directory of vaults and its recent-vault memory."""

    def __init__(self, address, root):
        super().__init__(address, ViewerHandler)
        self.root = Path(root)
        self.recent = RecentFile(root)
        #: The vault a `/catalog` request could not open, shown once on `/`.
        self.missing = None

    def vault_view(self, name):
        """The catalog view of vault `name`, or `None` when it cannot be read.

        Names are plain directory entries of the served root: anything that
        would reach outside it is treated as a vault that is not there.
        """
        if name in (".", "..") or "/" in name or "\\" in name:
            return None
        try:
            return load_view(str(self.root / name))
        except MvaultError:
            return None


class ViewerHandler(BaseHTTPRequestHandler):
    """Routes `/`, `/catalog/...` and `/vault/...` onto the served vaults."""

    server_version = "mvault-viewer"

    def do_GET(self):
        self.dispatch(self.route_get)

    def do_POST(self):
        self.dispatch(self.route_post)

    def do_PATCH(self):
        self.dispatch(self.route_annotation)

    def do_DELETE(self):
        self.dispatch(self.route_annotation)

    def dispatch(self, route):
        """Run one route, turning an unexpected failure into an error page."""
        try:
            route(segments(self.path))
        except Exception:  # a local viewer answers, it never reports a traceback
            self.message(HTTPStatus.INTERNAL_SERVER_ERROR, "Viewer error", FAILURE_MESSAGE)

    def route_get(self, parts):
        """`/` lands, `/catalog/...` is a vault page, `/vault/...` a saved file."""
        if not parts:
            self.landing()
        elif parts[0] == "vault" and len(parts) == 4:
            self.asset(parts[1], parts[2], parts[3])
        elif parts[0] != "catalog" or len(parts) > 4:
            self.message(HTTPStatus.NOT_FOUND, "No such page", NOT_FOUND_MESSAGE)
        elif len(parts) == 1:
            self.redirect("/")
        else:
            self.catalog(parts[1], parts[2:])

    def route_post(self, parts):
        """The landing form at `/`, or an annotation create on an entry route."""
        if parts:
            self.route_annotation(parts)
            return

        named = parse_qs(self.read_body()).get("catalog")
        self.redirect(catalog_route(named[0]) if named else "/")

    def route_annotation(self, parts):
        """An annotation method: it addresses one entry route and nothing else."""
        if len(parts) != 4 or parts[0] != "catalog":
            self.message(HTTPStatus.NOT_FOUND, "No such page", NOT_FOUND_MESSAGE)
            return

        name = parts[1]
        if self.server.vault_view(name) is None:
            self.server.missing = name
            self.redirect("/")
        else:
            self.apply_annotation(name, parts[2], parts[3])

    def apply_annotation(self, name, category, entry_id):
        """Carry out the annotation this request describes, then show the entry.

        The catalog, not the route, decides which category the entry ends up in:
        annotating a v1 vault migrates it, which moves the entry to `episodes`.
        """
        try:
            request = annotation_request(self.read_body())
            category, timecode = annotate(
                str(self.server.root / name), category, entry_id, self.command, request
            )
        except AnnotationError as error:
            self.message(error.status, "Annotation refused", str(error))
        except MvaultError as error:
            self.message(HTTPStatus.INTERNAL_SERVER_ERROR, "Annotation failed", str(error))
        else:
            self.redirect(entry_route(name, category, entry_id, timecode))

    def read_body(self):
        """The form-encoded request body as text."""
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length).decode("utf-8")

    def landing(self):
        """The landing page, carrying any pending vault-not-found notice."""
        missing, self.server.missing = self.server.missing, None
        names = merge(from_cookie(self.headers.get("Cookie")), self.server.recent.read())
        recent = [(name, vault_route(self.server, name)) for name in names]
        self.respond(HTTPStatus.OK, pages.landing_page(recent, missing))

    def catalog(self, name, rest):
        """A vault route: its default redirect, a category listing, an entry."""
        view = self.server.vault_view(name)
        if view is None:
            self.server.missing = name
            self.redirect("/")
            return

        cookie = self.record_visit(name)
        category = rest[0] if rest else None
        if category not in categories_for(view.version):
            self.redirect(default_route(name, view.version), cookie)
        elif len(rest) > 1:
            self.detail(name, view, category, rest[1], cookie)
        else:
            self.listing(name, view, category, cookie)

    def listing(self, name, view, category, cookie):
        """A category's entries, in catalog order."""
        stored = stored_names(self.server.root / name / MEDIA_DIR)
        body = pages.category_page(name, view, category, stored)
        self.respond(HTTPStatus.OK, body, cookie=cookie)

    def detail(self, name, view, category, entry_id, cookie):
        """One entry in full, looked up inside the named category alone."""
        entry = view.entry(category, entry_id)
        if entry is None:
            self.message(HTTPStatus.NOT_FOUND, "No such entry", NO_ENTRY_MESSAGE)
            return

        stored = stored_assets(self.server.root / name, entry_id)
        seek = timecode_query(self.path)
        self.respond(
            HTTPStatus.OK, detail_page(name, view, category, entry, stored, seek), cookie=cookie
        )

    def asset(self, name, kind, requested):
        """A vault's saved files: `media/<file>` and `preview/<id>`."""
        if kind not in ASSET_KINDS:
            self.message(HTTPStatus.NOT_FOUND, "No such page", NOT_FOUND_MESSAGE)
        elif self.server.vault_view(name) is None:
            self.server.missing = name
            self.redirect("/")
        else:
            directory, lookup = ASSET_KINDS[kind]
            self.send_asset(self.server.root / name / directory, lookup, requested)

    def send_asset(self, directory, lookup, requested):
        """Serve one saved file, refusing any name that leaves its directory."""
        if escapes(directory, requested):
            self.message(HTTPStatus.FORBIDDEN, "Refused", TRAVERSAL_MESSAGE)
            return

        found = lookup(directory, requested)
        if found is None:
            self.message(HTTPStatus.NOT_FOUND, "No such file", NO_FILE_MESSAGE)
        else:
            self.send_file(*found)

    def record_visit(self, name):
        """Remember a visit in both memories; returns the cookie to set."""
        self.server.recent.record(name)
        return to_cookie(promote(from_cookie(self.headers.get("Cookie")), name))

    def message(self, status, title, text):
        """Send a plain page for an outcome that has nothing to list."""
        self.respond(status, pages.message_page(title, text))

    def redirect(self, location, cookie=None):
        """Send a redirect the browser follows with a `GET`."""
        self.respond(HTTPStatus.SEE_OTHER, "", location=location, cookie=cookie)

    def respond(self, status, document, location=None, cookie=None):
        """Write one HTML response."""
        self.send_body(status, document.encode("utf-8"), HTML_TYPE, location, cookie)

    def send_file(self, path, content_type):
        """Write one saved file back as the response body."""
        self.send_body(HTTPStatus.OK, path.read_bytes(), content_type)

    def send_body(self, status, body, content_type, location=None, cookie=None):
        """Write one complete response."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if location:
            self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Stay quiet: the viewer is a local UI, not a logging web server."""
