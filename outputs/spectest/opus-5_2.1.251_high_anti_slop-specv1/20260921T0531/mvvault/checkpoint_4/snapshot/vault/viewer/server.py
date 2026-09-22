"""The viewer's HTTP server and the ``serve`` command that runs it."""

import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .. import links
from ..errors import VaultError
from . import recent, routes, vaults

CONTENT_TYPE = "text/html; charset=utf-8"


class ViewerHandler(BaseHTTPRequestHandler):
    """Hands each request to :mod:`vault.viewer.routes` and sends its response."""

    def do_GET(self):
        url = urlsplit(self.path)
        segments = [unquote(part) for part in url.path.split("/") if part]
        self._answer(routes.get, self.server.root, segments, parse_qs(url.query), self._visited())

    def do_POST(self):
        length = self.headers.get("Content-Length", "")
        body = self.rfile.read(int(length) if length.isdigit() else 0)
        self._answer(routes.post, parse_qs(body.decode("utf-8", errors="replace")))

    def log_message(self, *args):
        """Stay quiet: the viewer announced its URL when it started."""

    def _answer(self, route, *arguments):
        """Send what ``route`` answers, or an error page if it cannot answer.

        A request the viewer trips over still gets a well-formed response; the
        traceback stays on the terminal it was started from.
        """
        try:
            response = route(*arguments)
        except Exception:
            self.log_error("%s", traceback.format_exc())
            response = routes.failure()
        self._send(response)

    def _send(self, response):
        """Write one response, refreshing the recent-vault cookie if it names one."""
        body = response.html.encode("utf-8")
        self.send_response(response.status)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        if response.location:
            self.send_header("Location", response.location)
        if response.visited:
            self.send_header("Set-Cookie", recent.remember(self._visited(), response.visited))
        self.end_headers()
        self.wfile.write(body)

    def _visited(self):
        """The vaults the requesting browser already remembers."""
        return recent.visited(self.headers.get("Cookie", ""))


class ViewerServer(ThreadingHTTPServer):
    """An HTTP server that knows the directory the vaults it serves live in."""

    def __init__(self, address, root):
        super().__init__(address, ViewerHandler)
        self.root = root


def create(root, host, port):
    """Bind the viewer to ``host`` and ``port``, serving the vaults in ``root``."""
    try:
        return ViewerServer((host, port), root)
    except OSError as error:
        raise VaultError(f"viewer could not listen on {host}:{port}: {error}") from error


def serve(root, name, host, port):
    """Run the viewer until interrupted, opening a browser on its start page.

    Without a ``name`` the browser opens the landing page; with one it opens
    that vault's default category page straight away.
    """
    server = create(root, host, port)
    url = f"{links.SCHEME}://{host}:{port}{start_path(root, name)}"
    print(f"mvault viewer at {url}", flush=True)
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


def start_path(root, name):
    """The path the browser is sent to for the vault ``name``, if there is one.

    The default category is resolved up front when the vault can be read, so
    the browser lands on the listing rather than on a redirect to it.
    """
    view = vaults.read(root, name) if name else None
    if view is None:
        return links.catalog_path(name) if name else links.ROOT
    return links.category_path(name, vaults.default_category(view))
