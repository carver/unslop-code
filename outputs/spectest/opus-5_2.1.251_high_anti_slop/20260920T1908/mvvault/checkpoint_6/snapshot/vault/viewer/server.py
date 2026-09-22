"""The local HTTP server behind the viewer.

Every route reads a vault in the version it is stored in, so browsing a
version 1 or version 2 vault never migrates it. A request that names no
readable vault lands back on the landing page rather than on an error, and
every other failure answers with a page rather than a traceback.

Beside the catalog pages the server hands out the files a vault has
downloaded, under ``/vault/<name>/``, so an entry's page can show its preview
and play its media.

An entry's own address is also where its annotations are written, which is the
one thing the viewer stores: ``POST``, ``PATCH`` and ``DELETE`` there add,
change and drop them. Annotations only exist in version 3, so writing one to
an older vault migrates it.
"""

import json
import sys
import webbrowser
from collections.abc import Iterable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from ..annotations import AnnotationError, apply_annotation
from ..errors import ServerError, VaultError
from ..views import CatalogView, read_view
from .assets import content_type, is_plain_name, media_asset, preview_asset
from .detail import entry_detail
from .links import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    LANDING_PATH,
    MEDIA_SEGMENT,
    PREVIEW_SEGMENT,
    VAULT_ROOT,
    base_url,
    catalog_path,
    category_path,
    entry_path,
)
from .listing import entry_rows
from .pages import FORM_FIELD, MISSING_PARAM, category_page, detail_page, error_page, landing_page
from .recents import read_recent, visit_cookie

CATALOG_ROOT = "catalog"
MAX_CATALOG_SEGMENTS = 3
VAULT_FILE_SEGMENTS = 3

ASSET_LOOKUPS = {MEDIA_SEGMENT: media_asset, PREVIEW_SEGMENT: preview_asset}


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
        elif segments[:1] == [VAULT_ROOT]:
            self._vault_file(segments[1:])
        elif segments:
            self._not_found()
        else:
            self._landing(_first(parse_qs(url.query), MISSING_PARAM))

    def do_POST(self) -> None:
        """Take the landing page's form, or write a new annotation on an entry."""
        if _segments(urlsplit(self.path).path):
            self._annotation("POST")
            return
        fields = parse_qs(self._body().decode("utf-8", "replace"))
        name = _first(fields, FORM_FIELD, "").strip()
        self._redirect(catalog_path(name) if name else LANDING_PATH)

    def do_PATCH(self) -> None:
        """Change the title or body of one annotation of an entry."""
        self._annotation("PATCH")

    def do_DELETE(self) -> None:
        """Drop one annotation of an entry."""
        self._annotation("DELETE")

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
        if len(rest) == 2:
            self._entry(name, view, rest[0], entries, rest[1])
            return
        rows = entry_rows(self.server.root / name, view, entries)
        self._html(category_page(name, view, rest[0], rows), visited=name)

    def _entry(
        self, name: str, view: CatalogView, category: str, entries: list, entry_id: str
    ) -> None:
        """Show one entry of one category, or say that this category has no such entry.

        Only the category named in the address is searched, so the same id in
        another category of the vault does not answer here.
        """
        detail = entry_detail(self.server.root / name, view, entries, entry_id)
        if detail is None:
            self._error(
                HTTPStatus.NOT_FOUND, f"The {category} of '{name}' hold no entry '{entry_id}'."
            )
            return
        self._html(detail_page(name, view, category, detail), visited=name)

    def _annotation(self, method: str) -> None:
        """Write one annotation of ``/catalog/<name>/<category>/<id>`` and answer with its page.

        The address names the category the entry is stored under when the
        request arrives, which for an older vault is the category that version
        has. Writing the annotation migrates such a vault, so the entry ends up
        in the version 3 category the redirect names.
        """
        segments = _segments(urlsplit(self.path).path)
        if segments[:1] != [CATALOG_ROOT] or len(segments) != 1 + MAX_CATALOG_SEGMENTS:
            self._not_found()
            return
        name, category, entry_id = segments[1:]
        view = self._view(name)
        if view is None:
            self._redirect(f"{LANDING_PATH}?{urlencode({MISSING_PARAM: name})}")
            return
        migrated = view.migrated_category(category)
        if migrated is None:
            self._error(HTTPStatus.NOT_FOUND, f"'{name}' has no '{category}' to annotate.")
            return
        self._write_annotation(name, migrated, entry_id, method)

    def _write_annotation(self, name: str, category: str, entry_id: str, method: str) -> None:
        """Apply one annotation request, reporting what a vault refused to store.

        A request the vault cannot read is answered as the bad request it is,
        and a migration that the annotation could not carry out is reported as
        the server failure it is; either way nothing was written.
        """
        try:
            timecode = apply_annotation(
                self.server.root / name, category, entry_id, method, self._annotation_fields()
            )
        except AnnotationError as error:
            self._error(error.status, str(error))
        except VaultError as error:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"'{name}' was left as it was: {error}")
        else:
            self._redirect(entry_path(name, category, entry_id, timecode), visited=name)

    def _annotation_fields(self) -> dict:
        """The JSON object an annotation request carries."""
        try:
            fields = json.loads(self._body().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AnnotationError(f"the request body is not JSON: {error}") from error
        if not isinstance(fields, dict):
            raise AnnotationError("the request body is not a JSON object")
        return fields

    def _body(self) -> bytes:
        """The bytes of a request body, as long as its headers say it is."""
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _vault_file(self, segments: list[str]) -> None:
        """Serve ``/vault/<name>/media/<file>`` or ``/vault/<name>/preview/<id>``.

        The last segment names one file of the vault directory it is looked up
        in; one that has been decorated into a path leads somewhere else and is
        refused rather than resolved.
        """
        if len(segments) != VAULT_FILE_SEGMENTS:
            self._not_found()
            return
        name, kind, target = segments
        lookup = ASSET_LOOKUPS.get(kind)
        if lookup is None:
            self._not_found()
            return
        if self._view(name) is None:
            self._redirect(f"{LANDING_PATH}?{urlencode({MISSING_PARAM: name})}")
            return
        if not is_plain_name(target):
            self._error(HTTPStatus.FORBIDDEN, f"'{target}' does not name a file of '{name}'.")
            return
        path = lookup(self.server.root / name, target)
        if path is None:
            self._not_found()
            return
        self._respond(
            HTTPStatus.OK, path.read_bytes(), [("Content-Type", content_type(path.name))]
        )

    def _view(self, name: str) -> CatalogView | None:
        """Read the vault called ``name``, or ``None`` when this root has no such vault."""
        if not is_plain_name(name):
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
        self._error(HTTPStatus.NOT_FOUND, f"There is nothing at {self.path}.")

    def _error(self, status: HTTPStatus, message: str) -> None:
        """Answer a refused request with a page saying what it asked for."""
        self._html(error_page(status, message), status)

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
