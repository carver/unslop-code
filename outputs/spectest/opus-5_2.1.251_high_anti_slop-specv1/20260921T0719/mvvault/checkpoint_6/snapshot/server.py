"""The ``serve`` command: a local HTTP viewer for the vaults of a directory.

The server holds no state of its own.  Every request is answered from the
vaults on disk as they stand, so a vault synced while the viewer runs shows
its new entries on the next page load, whatever version it is written in.
"""

import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

import responses
import routes
from errors import MvaultError
from responses import Response
from viewer import DEFAULT_HOST, DEFAULT_PORT


def serve_vaults(
    name: Optional[str] = None, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> str:
    """Serve the vaults of the working directory until interrupted.

    A browser is opened on the landing page, or on the page vault ``name``
    opens on, under the host the server was asked to listen on and the port
    it ended up bound to.
    """
    directory = Path.cwd()
    server = viewer_server(directory, host, port)
    url = f"http://{host}:{server.server_address[1]}{routes.start_path(directory, name)}"
    print(f"Serving the mvault viewer at {url}", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    return "Stopped the mvault viewer"


def viewer_server(directory: Path, host: str, port: int) -> ThreadingHTTPServer:
    """Bind a viewer server for ``directory`` without starting to serve."""
    try:
        return ThreadingHTTPServer((host, port), partial(ViewerHandler, directory=directory))
    except OSError as error:
        raise MvaultError(f"Cannot serve the viewer on {host}:{port}: {error}") from error


class ViewerHandler(BaseHTTPRequestHandler):
    """Answers viewer requests about the vaults of one directory."""

    server_version = "mvault"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args: Any, directory: Path, **kwargs: Any):
        self.directory = directory
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        """Answer a request for a page."""
        self._send(self._answered(lambda: routes.get(self.directory, self.path)))

    def do_POST(self) -> None:
        """Answer the landing page form, or add an annotation to an entry."""
        self._send(self._answered(lambda: routes.post(self.directory, self.path, self._body())))

    def do_PATCH(self) -> None:
        """Answer a request to rewrite one annotation of an entry."""
        self._send(self._answered(lambda: routes.patch(self.directory, self.path, self._body())))

    def do_DELETE(self) -> None:
        """Answer a request to drop one annotation of an entry."""
        self._send(self._answered(lambda: routes.delete(self.directory, self.path, self._body())))

    def _answered(self, route: Callable[[], Response]) -> Response:
        """Run one route, turning a request it breaks on into a page.

        The visitor is told that the request failed and nothing more; what
        exactly went wrong belongs in the log of whoever started the server.
        """
        try:
            return route()
        except Exception as error:
            self.log_error("%s failed: %s", self.path, error)
            return responses.FAILURE

    def _body(self) -> str:
        """Read the body of a request, form-encoded or JSON as the route needs."""
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length).decode("utf-8", errors="replace")

    def _send(self, response: Response) -> None:
        """Write one response out, under the content type it names."""
        self.send_response(response.status)
        if response.location:
            self.send_header("Location", response.location)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)
