"""The local viewer HTTP server and its browser entry point.

The handler only moves bytes: it hands the request to :mod:`vault.routes`, one
method at a time, and writes back the response that comes out.
"""

import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import routes, viewer
from .recent import RecentVaults


def serve(name, host, port):
    """Run the viewer on ``host:port`` until interrupted, opening a browser on its first page."""
    server = ThreadingHTTPServer((host, port), partial(ViewerHandler, store=RecentVaults()))
    start = viewer.vault_path(name) if name else routes.HOME
    print(f"mvault viewer on http://{host}:{port}{start} - press Ctrl+C to stop")
    webbrowser.open(f"http://{host}:{port}{start}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


class ViewerHandler(BaseHTTPRequestHandler):
    """Serves the viewer pages, recording visited vaults in the shared recent-vault store."""

    server_version = "mvault-viewer"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, store, **kwargs):
        self.store = store
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """Answer a page request."""
        self._respond(routes.get_page(self.path, self.store))

    def do_POST(self):
        """Answer a form submission, or an annotation created on an entry page."""
        self._respond(routes.post(self.path, self._body()))

    def do_PATCH(self):
        """Answer an annotation update."""
        self._respond(routes.patch(self.path, self._body()))

    def do_DELETE(self):
        """Answer an annotation deletion."""
        self._respond(routes.delete(self.path, self._body()))

    def _body(self):
        """Read the request body, which is empty when the request carries none."""
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length).decode("utf-8")

    def _respond(self, response):
        """Write a routed response back to the client."""
        self.send_response(response.status)
        for header, value in response.headers:
            self.send_header(header, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)
