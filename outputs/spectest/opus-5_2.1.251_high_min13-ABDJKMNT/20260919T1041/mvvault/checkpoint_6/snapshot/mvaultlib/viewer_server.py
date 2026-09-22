"""The `serve` command: a local HTTP viewer for the vaults in one directory."""

import threading
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import viewer_routes
from .errors import ServerError
from .viewer_links import DEFAULT_HOST, DEFAULT_PORT, SCHEME

#: A form body carries a vault name and an annotation body one note; more is ignored.
MAX_BODY = 64 * 1024


class ViewerHandler(BaseHTTPRequestHandler):
    """Writes out whatever :mod:`mvaultlib.viewer_routes` decides on."""

    server_version = "mvault-viewer"
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._answer(viewer_routes.get)

    def do_POST(self):
        self._answer(viewer_routes.post)

    def do_PATCH(self):
        self._answer(viewer_routes.patch)

    def do_DELETE(self):
        self._answer(viewer_routes.delete)

    def _answer(self, route):
        """Route the request, and never let a failure reach the browser raw."""
        try:
            response = route(self._request())
        except Exception as error:  # a viewer answers with a page, not a traceback
            self.log_error("request failed: %s", error)
            response = viewer_routes.error_page(500, "The viewer could not answer that request.")
        self._write(response)

    def _request(self):
        parts = urlsplit(self.path)
        body = self._body()
        return viewer_routes.Request(
            path=parts.path,
            query=parse_qs(parts.query),
            form=parse_qs(body),
            body=body,
            cookies={key: morsel.value for key, morsel in SimpleCookie(self.headers.get("Cookie", "")).items()},
        )

    def _body(self):
        """The request body, as far as a form or an annotation can reach."""
        length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
        return self.rfile.read(length).decode("utf-8", errors="replace")

    def _write(self, response):
        self.send_response(response.status)
        for header, value in response.headers:
            self.send_header(header, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, *args):
        """Keep the terminal for the serve banner, not for a request log."""


def serve(name, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """Serve the vaults in the working directory until the process is stopped.

    The browser is opened from a separate thread once the socket is bound, so
    a browser command that does not return cannot keep the viewer from serving.
    """
    server = _bound(host, port)
    url = f"{SCHEME}://{host}:{port}{start_path(name)}"
    print(f"mvault: serving {url}")

    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("mvault: viewer stopped")
    finally:
        server.server_close()


def _bound(host, port):
    """The viewer's server, or a readable error when the address is taken."""
    try:
        return ThreadingHTTPServer((host, port), ViewerHandler)
    except OSError as problem:
        raise ServerError(f"could not serve on {host}:{port}: {problem}") from None


def start_path(name):
    """Where the browser is pointed: `/`, or the vault's default category page."""
    return viewer_routes.default_route(name) if name else "/"
