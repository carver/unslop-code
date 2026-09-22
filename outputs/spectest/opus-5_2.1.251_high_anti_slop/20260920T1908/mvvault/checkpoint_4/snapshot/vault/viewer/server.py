"""The local HTTP server behind the viewer.

Every route reads a vault in the version it is stored in, so browsing a
version 1 or version 2 vault never migrates it. A request that names no
readable vault lands back on the landing page rather than on an error.
"""

import sys
import webbrowser
from collections.abc import Iterable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from ..errors import ServerError, VaultError
from ..views import CatalogView, read_view
from .links import DEFAULT_HOST, DEFAULT_PORT, LANDING_PATH, base_url, catalog_path, category_path
from .listing import entry_rows
from .pages import FORM_FIELD, MISSING_PARAM, category_page, error_page, landing_page
from .recents import read_recent, visit_cookie

CATALOG_ROOT = "catalog"
MAX_CATALOG_SEGMENTS = 3


def serve(root: Path, name: str | None, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Serve the vaults under ``root`` until interrupted, opening a browser at ``name``.

    The browser starts on that vault's default category page, or on the
    landing page when no vault was named.
    """
    try:
        server = ViewerServer((host, port), root)
    except OSError as error:
        raise ServerError(f"could not serve on {host}:{port}: {error}") from error
    origin = base_url(host, port)
    print(f"mvault is serving '{root}' at {origin}{LANDING_PATH} (press Ctrl-C to stop)")
    webbrowser.open(origin + _start_path(root, name))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


class ViewerHandler(BaseHTTPRequestHandler):
    """Answers the landing page, the catalog routes and nothing else."""

    server_version = "mvault-viewer"

    def do_GET(self) -> None:
        """Serve the landing page, or one vault's catalog."""
        url = urlsplit(self.path)
        segments = _segments(url.path)
        if segments[:1] == [CATALOG_ROOT]:
            self._catalog(segments[1:])
        elif segments:
            self._not_found()
        else:
            self._landing(_first(parse_qs(url.query), MISSING_PARAM))

    def do_POST(self) -> None:
        """Take the landing page's form and send the browser to the vault it names."""
        if _segments(urlsplit(self.path).path):
            self._not_found()
            return
        length = int(self.headers.get("Content-Length") or 0)
        fields = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        name = _first(fields, FORM_FIELD, "").strip()
        self._redirect(catalog_path(name) if name else LANDING_PATH)

    def log_message(self, format: str, *args) -> None:
        """Log requests the way the rest of mvault reports on stderr."""
        print(f"mvault: {format % args}", file=sys.stderr)

    def _landing(self, missing: str | None) -> None:
        """Show the vault form, plus the vaults this browser has opened before."""
        recent = [
            (name, category_path(name, view.default_category))
            for name in read_recent(self.headers.get("Cookie"))
            if (view := self._view(name))
        ]
        self._html(landing_page(recent, missing))

    def _catalog(self, segments: list[str]) -> None:
        """Serve ``/catalog/<name>[/<category>[/<id>]]`` for a stored vault.

        A vault that cannot be read sends the browser back to the landing page,
        and a category this catalog version does not have falls back to the
        vault's default one.
        """
        if not 1 <= len(segments) <= MAX_CATALOG_SEGMENTS:
            self._not_found()
            return
        name, *rest = segments
        view = self._view(name)
        if view is None:
            self._redirect(f"{LANDING_PATH}?{urlencode({MISSING_PARAM: name})}")
            return
        entries = view.entries_in(rest[0]) if rest else None
        if entries is None:
            self._redirect(category_path(name, view.default_category), visited=name)
            return
        rows = entry_rows(self.server.root / name, view, entries)
        page = category_page(name, view, rest[0], rows, rest[1] if len(rest) > 1 else None)
        self._html(page, visited=name)

    def _view(self, name: str) -> CatalogView | None:
        """Read the vault called ``name``, or ``None`` when this root has no such vault."""
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            return None
        try:
            return read_view(self.server.root / name)
        except VaultError:
            return None

    def _html(self, page: str, status: HTTPStatus = HTTPStatus.OK, visited: str | None = None) -> None:
        self._respond(
            status,
            page.encode("utf-8"),
            [("Content-Type", "text/html; charset=utf-8"), *self._visit(visited)],
        )

    def _redirect(self, location: str, visited: str | None = None) -> None:
        self._respond(HTTPStatus.SEE_OTHER, headers=[("Location", location), *self._visit(visited)])

    def _not_found(self) -> None:
        self._html(
            error_page(HTTPStatus.NOT_FOUND, f"There is no page at {self.path}."),
            HTTPStatus.NOT_FOUND,
        )

    def _visit(self, visited: str | None) -> list[tuple[str, str]]:
        """The ``Set-Cookie`` header a response records a vault visit with, if it is one."""
        if visited is None:
            return []
        recent = read_recent(self.headers.get("Cookie"))
        return [("Set-Cookie", visit_cookie(recent, visited))]

    def _respond(
        self, status: HTTPStatus, body: bytes = b"", headers: Iterable[tuple[str, str]] = ()
    ) -> None:
        """Send one complete response: status line, headers, body."""
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        for header, value in headers:
            self.send_header(header, value)
        self.end_headers()
        self.wfile.write(body)


class ViewerServer(ThreadingHTTPServer):
    """An HTTP server that serves the vault directories of one root."""

    def __init__(self, address: tuple[str, int], root: Path):
        super().__init__(address, ViewerHandler)
        self.root = root


def _start_path(root: Path, name: str | None) -> str:
    """The page ``serve`` opens the browser on.

    A named vault resolves to its own default category page; one that cannot
    be read falls back to the route that sends the browser back to the landing
    page with a vault-not-found notice.
    """
    if name is None:
        return LANDING_PATH
    try:
        return category_path(name, read_view(root / name).default_category)
    except VaultError:
        return catalog_path(name)


def _segments(path: str) -> list[str]:
    """The non-empty, decoded path segments of a request."""
    return [unquote(segment) for segment in path.split("/") if segment]


def _first(fields: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    """The first value of a parsed query or form field."""
    return fields.get(name, [default])[0]
