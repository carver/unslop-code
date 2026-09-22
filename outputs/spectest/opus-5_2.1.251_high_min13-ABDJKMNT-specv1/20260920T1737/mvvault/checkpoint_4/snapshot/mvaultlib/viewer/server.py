"""The `serve` command: a local HTTP viewer for vaults of any supported version.

Vaults are read through `CatalogView`, so nothing the viewer shows requires a
migrated catalog, and nothing it does writes to a vault. A request that names a
vault or a category the server cannot serve is answered with a redirect, never
with an exception.
"""

import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from mvaultlib.catalog import read_raw_catalog
from mvaultlib.errors import MvaultError
from mvaultlib.viewer.links import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCHEME,
    catalog_path,
    default_category,
)
from mvaultlib.viewer.listing import listed_entries
from mvaultlib.viewer.pages import category_page, landing_page
from mvaultlib.viewer.recent import RecentVaults
from mvaultlib.views import build_view

#: Status used for every viewer redirect, including the form submission.
REDIRECT_STATUS = HTTPStatus.SEE_OTHER


def serve_vault(name=None, host=DEFAULT_HOST, port=DEFAULT_PORT, directory=None, out=sys.stdout):
    """Serve `directory` until interrupted, opening a browser on the start page."""
    root = Path(directory) if directory else Path.cwd()
    try:
        server = ViewerServer((host, port), root)
    except OSError as error:
        raise MvaultError(f"cannot serve on {host}:{port}: {error}") from error

    url = f"{DEFAULT_SCHEME}://{host}:{port}{start_path(root, name)}"
    print(f"mvault: serving {root} at {url}", file=out, flush=True)
    # The socket is already listening, so a browser that is quick to connect is
    # simply queued until `serve_forever` starts accepting.
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    with server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def start_path(root, name):
    """The path the browser opens: `/`, or the vault's default category page."""
    if name is None:
        return "/"
    return catalog_path(name, _stored_default_category(root, name))


def vault_path(root, name):
    """The directory of `name`, or None when the name is not a child of `root`."""
    candidate = root / name
    return candidate if candidate.parent == root else None


def _read_view(root, name):
    """The view of a named vault, or None when the viewer cannot read it."""
    vault = vault_path(root, name)
    if vault is None:
        return None
    try:
        return build_view(name, read_raw_catalog(str(vault)))
    except MvaultError:
        return None


def _stored_default_category(root, name):
    """The default category of a vault, or None when it cannot be read."""
    view = _read_view(root, name)
    return default_category(view.version) if view else None


class ViewerServer(ThreadingHTTPServer):
    """The viewer's server, holding the state its pages read between requests."""

    daemon_threads = True

    def __init__(self, address, root):
        super().__init__(address, ViewerHandler)
        self.root = root
        self.recent = RecentVaults(root)
        self.missing_vault = None

    def take_missing_vault(self):
        """The vault a redirect reported as missing, cleared once it is shown."""
        missing, self.missing_vault = self.missing_vault, None
        return missing

    def recent_links(self):
        """The visited vaults as `(name, path)` pairs, newest visit first."""
        return [
            (name, catalog_path(name, _stored_default_category(self.root, name)))
            for name in self.recent.names()
        ]


class ViewerHandler(BaseHTTPRequestHandler):
    """Routes `/` and `/catalog/...`; every other path is a plain 404."""

    server_version = "mvault-viewer"

    def do_GET(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        segments = _path_segments(self.path)
        if not segments:
            self._landing()
        elif segments[0] == "catalog" and 2 <= len(segments) <= 4:
            self._catalog(*segments[1:])
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown viewer path")

    def do_POST(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        if _path_segments(self.path):
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown viewer path")
            return
        length = int(self.headers.get("Content-Length") or 0)
        fields = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        name = fields.get("catalog", [""])[0].strip()
        self._redirect(catalog_path(name) if name else "/")

    def _landing(self):
        """The landing page, which also reports the last vault that was missing."""
        missing = self.server.take_missing_vault()
        self._html(landing_page(self.server.recent_links(), missing))

    def _catalog(self, name, category=None, entry_id=None):
        """One vault route: the listing, or a redirect that resolves the route."""
        view = _read_view(self.server.root, name)
        if view is None:
            self.server.missing_vault = name
            self._redirect("/")
            return
        self.server.recent.record(name)
        group = view.group(category)
        if group is None:
            self._redirect(catalog_path(name, default_category(view.version)))
            return
        entries = listed_entries(view, group, vault_path(self.server.root, name))
        self._html(category_page(name, view, group, entries, entry_id))

    def _redirect(self, location):
        self.send_response(REDIRECT_STATUS)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _html(self, markup):
        payload = markup.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        """Keep the viewer quiet; it shares the terminal with the CLI."""


def _path_segments(target):
    """The decoded path segments of a request target, without empty ones."""
    return [unquote(part) for part in urlparse(target).path.split("/") if part]
