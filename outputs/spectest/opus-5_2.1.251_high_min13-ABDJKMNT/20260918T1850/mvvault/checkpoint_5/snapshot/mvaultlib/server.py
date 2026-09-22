"""The local viewer: request routing, the HTTP server, and the `serve` command.

Routing is kept in `Viewer`, which turns a request into a `Response` without
touching a socket; the handler below only moves bytes. Every route answers with
a page, a file, or a redirect, so a browser never meets a traceback.
"""

import sys
import threading
import traceback
import webbrowser
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote

from .assets import ASSET_READERS, UnsafePath
from .detail import EntryNotFound, entry_detail
from .errors import MvaultError
from .links import (
    ASSET_PREFIX,
    CATALOG_PREFIX,
    DEFAULT_HOST,
    DEFAULT_PORT,
    LANDING_PATH,
    MISSING_FIELD,
    catalog_path,
    category_path,
    missing_path,
    viewer_url,
)
from .pages import category_page, entry_page, error_page, landing_page
from .recent import RecentVaults, from_cookie, merge, to_cookie
from .viewer import Listing, VaultNotFound, category_rows, open_vault

#: Redirect statuses: 302 keeps a GET a GET, 303 turns a POST into one.
FOUND = 302
SEE_OTHER = 303

#: Deepest `/catalog/...` route: a vault, one of its categories, and one entry.
CATALOG_DEPTH = 3

#: A `/vault/...` route always names a vault, a kind of asset, and one target.
ASSET_DEPTH = 3

#: What every page is sent as; assets carry the type of the file itself.
HTML_TYPE = "text/html; charset=utf-8"


@dataclass(frozen=True)
class Response:
    """What a route decided, before it becomes bytes on the wire.

    `recent` is the recent-vault list to hand back to the browser; an empty one
    leaves whatever the browser already stores alone. A `body` is page text
    unless the route served a file, in which case it is the file's bytes.
    """

    status: int = 200
    body: str | bytes = ""
    location: str | None = None
    recent: tuple = ()
    content_type: str = HTML_TYPE


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
        if segments[0] == CATALOG_PREFIX:
            return self._catalog(segments[1:], cookie)
        if segments[0] == ASSET_PREFIX:
            return self._asset(segments[1:])
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
        name, category, entry_id = (parts + [None, None])[:CATALOG_DEPTH]
        data, form = open_vault(self.root, name)
        if category not in form.categories:
            return redirect(category_path(name, form.default_category))
        if entry_id is not None:
            return self._entry(name, data, form, category, entry_id)

        listing = Listing(
            name=name,
            version=form.version,
            categories=form.categories,
            category=category,
            rows=category_rows(self.root, name, data, form, category),
        )
        return Response(body=category_page(listing))

    def _entry(self, name, data, form, category, entry_id):
        """One entry's detail page, or a refusal when the category has no such entry."""
        try:
            detail = entry_detail(self.root, name, data, form, category, entry_id)
        except EntryNotFound as error:
            return Response(status=404, body=error_page(str(error)))
        return Response(body=entry_page(detail))

    def _asset(self, parts):
        """The `/vault/<name>/media/<file>` and `/vault/<name>/preview/<id>` routes."""
        if len(parts) != ASSET_DEPTH or parts[1] not in ASSET_READERS:
            return Response(status=404, body=error_page("No such vault file."))

        name, kind, target = parts
        try:
            asset = ASSET_READERS[kind](self.root, name, target)
        except VaultNotFound:
            return redirect(missing_path(name))
        except UnsafePath:
            return Response(status=403, body=error_page("That path is not allowed."))

        if asset is None:
            return Response(status=404, body=error_page(f"No {kind} file for {target!r}."))
        return Response(body=asset.content, content_type=asset.content_type)


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
        payload = response.body if isinstance(response.body, bytes) else response.body.encode()
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
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
