"""The local viewer: request routing, the HTTP server, and the `serve` command.

Routing is kept in `Viewer`, which turns a request into a `Response` without
touching a socket; the handler below only moves bytes. Every route answers with
a page or a redirect, so a browser never meets a traceback.
"""

import sys
import threading
import traceback
import webbrowser
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote

from .errors import MvaultError
from .links import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    LANDING_PATH,
    MISSING_FIELD,
    catalog_path,
    category_path,
    missing_path,
    viewer_url,
)
from .pages import category_page, error_page, landing_page
from .recent import RecentVaults, from_cookie, merge, to_cookie
from .viewer import Listing, VaultNotFound, category_rows, open_vault

#: Redirect statuses: 302 keeps a GET a GET, 303 turns a POST into one.
FOUND = 302
SEE_OTHER = 303

#: Deepest `/catalog/...` route: a vault, one of its categories, and one entry.
CATALOG_DEPTH = 3


@dataclass(frozen=True)
class Response:
    """What a route decided, before it becomes bytes on the wire.

    `recent` is the recent-vault list to hand back to the browser; an empty one
    leaves whatever the browser already stores alone.
    """

    status: int = 200
    body: str = ""
    location: str | None = None
    recent: tuple = ()


def redirect(location, status=FOUND):
    """A redirect response; the browser keeps whatever page it was sent from."""
    return Response(status=status, location=location)


class Viewer:
    """Maps viewer requests onto responses, independent of the HTTP plumbing."""

    def __init__(self, root):
        self.root = Path(root)
        self.recent = RecentVaults()

    def get(self, target, cookie=""):
        """Answer a GET for `target`, the request path with any query string."""
        path, _, query = target.partition("?")
        segments = [unquote(part) for part in path.split("/") if part]
        if not segments:
            return self._landing(query, cookie)
        if segments[0] == "catalog":
            return self._catalog(segments[1:], cookie)
        return Response(status=404, body=error_page(f"No page at {path}."))

    def post(self, target, body):
        """Answer the landing page's form submission."""
        if target != LANDING_PATH:
            return Response(status=404, body=error_page(f"Nothing to post to {target}."))
        name = parse_qs(body).get("catalog", [""])[0].strip()
        return redirect(catalog_path(name) if name else LANDING_PATH, status=SEE_OTHER)

    def _landing(self, query, cookie):
        """The landing page, showing the vaults this browser has been to."""
        names = merge(from_cookie(cookie), self.recent.names)
        recent = [(name, default_path(self.root, name)) for name in names]
        missing = parse_qs(query).get(MISSING_FIELD, [None])[0]
        return Response(body=landing_page(recent, missing), recent=names)

    def _catalog(self, parts, cookie):
        """The `/catalog/<name>[/<category>[/<id>]]` routes."""
        if not parts:
            return redirect(LANDING_PATH)
        if len(parts) > CATALOG_DEPTH:
            return Response(status=404, body=error_page("No such catalog page."))

        name = parts[0]
        try:
            response = self._vault_response(parts)
        except VaultNotFound:
            return redirect(missing_path(name))

        self.recent.visit(name)
        return replace(response, recent=merge((name,), from_cookie(cookie), self.recent.names))

    def _vault_response(self, parts):
        """The page or redirect one readable vault's route resolves to."""
        name, *rest = parts
        data, form = open_vault(self.root, name)
        if not rest or rest[0] not in form.categories:
            return redirect(category_path(name, form.default_category))

        listing = Listing(
            name=name,
            version=form.version,
            categories=form.categories,
            category=rest[0],
            rows=category_rows(self.root, name, data, form, rest[0]),
        )
        return Response(body=category_page(listing, rest[1] if len(rest) > 1 else None))


class ViewerHandler(BaseHTTPRequestHandler):
    """Hands each request to the server's `Viewer` and writes its response out."""

    protocol_version = "HTTP/1.1"
    server_version = "mvault"

    def do_GET(self):
        self._answer(lambda viewer: viewer.get(self.path, self.headers.get("Cookie", "")))

    def do_POST(self):
        self._answer(lambda viewer: viewer.post(self.path, self._body()))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length).decode("utf-8", errors="replace")

    def _answer(self, route):
        """Send what the route produced; an unforeseen failure stays server-side."""
        try:
            response = route(self.server.viewer)
        except Exception:  # a browser gets a page; the traceback stays on stderr
            traceback.print_exc(file=sys.stderr)
            response = Response(status=500, body=error_page("The viewer failed to answer."))
        self._send(response)

    def _send(self, response):
        payload = response.body.encode("utf-8")
        self.send_response(response.status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if response.location:
            self.send_header("Location", response.location)
        if response.recent:
            self.send_header("Set-Cookie", to_cookie(response.recent))
        self.end_headers()
        self.wfile.write(payload)


class ViewerServer(ThreadingHTTPServer):
    """An HTTP server carrying the `Viewer` its handlers answer from."""

    daemon_threads = True

    def __init__(self, address, root):
        super().__init__(address, ViewerHandler)
        self.viewer = Viewer(root)


def default_path(root, name):
    """Where a vault's link goes: its default category page, while it is readable.

    A vault that cannot be read keeps its plain catalog link, which redirects to
    the landing page and says so there.
    """
    try:
        _, form = open_vault(root, name)
    except VaultNotFound:
        return catalog_path(name)
    return category_path(name, form.default_category)


def run_viewer(name=None, host=DEFAULT_HOST, port=DEFAULT_PORT, root=None):
    """Serve the vaults in `root` until interrupted, opening a browser on the way in."""
    root = Path.cwd() if root is None else Path(root)
    try:
        server = ViewerServer((host, port), root)
    except OSError as error:
        raise MvaultError(f"cannot serve on {host}:{port}: {error}") from error

    opening = LANDING_PATH if name is None else default_path(root, name)
    print(f"mvault: serving {root} at {viewer_url(LANDING_PATH, host, port)}", flush=True)
    threading.Thread(
        target=webbrowser.open, args=(viewer_url(opening, host, port),), daemon=True
    ).start()
    with server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("mvault: stopped", flush=True)
