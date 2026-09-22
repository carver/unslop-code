"""Shared fixtures for the mvault spec tests.

Every test drives the real CLI surface required by the spec:

    | Console command | `python mvault.py <subcommand> [args...]` | Full CLI behavior |

so the helpers here run `mvault.py` as a subprocess and serve the vault
`source` URL from a real local HTTP server (the spec requires the fetch be an
HTTP `GET` made with `urllib.request`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MVAULT = REPO_ROOT / "mvault.py"

# | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

TRACKED_FIELDS = ("title", "description", "views", "likes", "preview", "removed")
STATIC_FIELDS = ("id", "published", "width", "height")
CATEGORIES = ("episodes", "streams", "clips")

# | Media | `<source>/media/<entry_id>` | ... | Preview | `<source>/preview/<entry_id>` |
SOURCE_DOC_PATH = "/source.json"


def media_path(entry_id, fmt=None):
    """Request path the download phase must use for an entry's media."""
    suffix = f".{fmt}" if fmt else ""
    return f"{SOURCE_DOC_PATH}/media/{entry_id}{suffix}"


def preview_path(entry_id):
    """Request path the download phase must use for an entry's preview."""
    return f"{SOURCE_DOC_PATH}/preview/{entry_id}"


def media_dir(vault):
    return Path(vault) / "media"


def preview_dir(vault):
    return Path(vault) / "previews"


def listing(directory):
    """Sorted file names in a directory (empty when the directory is absent)."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(item.name for item in directory.iterdir() if item.is_file())


def make_source_entry(entry_id: str, **overrides):
    """A source entry carrying all nine required fields with valid types."""
    entry = {
        "id": entry_id,
        "published": "2024-05-01T08:30:00",
        "width": 1920,
        "height": 1080,
        "title": f"Title {entry_id}",
        "description": f"Description {entry_id}",
        "views": 100,
        "likes": 10,
        "preview": f"hash-{entry_id}",
    }
    entry.update(overrides)
    return entry


def make_payload(episodes=None, streams=None, clips=None):
    """A source response: JSON object with `episodes`, `streams`, `clips`."""
    return {
        "episodes": list(episodes or []),
        "streams": list(streams or []),
        "clips": list(clips or []),
    }


class SourceServer:
    """Serves the vault source payload over real HTTP."""

    def __init__(self):
        self.payload = make_payload()
        self.raw_body = None  # when set, served verbatim instead of `payload`
        self.status = 200
        self.requests = []  # (method, path) of every received request
        # Download assets: request path -> (status, body bytes, Content-Type).
        self.assets = {}
        # Request path -> number of remaining transient (5xx) responses to
        # serve before the registered asset is returned.
        self.transient = {}
        self.transient_status = 503
        self.missing_status = 404  # served for unregistered asset paths
        self._lock = threading.Lock()

        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                with server._lock:
                    server.requests.append(("GET", self.path))
                    if self.path == SOURCE_DOC_PATH:
                        asset = None
                        status = server.status
                        if server.raw_body is not None:
                            body = server.raw_body
                            if isinstance(body, str):
                                body = body.encode("utf-8")
                        else:
                            body = json.dumps(server.payload).encode("utf-8")
                        ctype = "application/json"
                    else:
                        asset = server._resolve_asset(self.path)
                        status, body, ctype = asset

                self.send_response(status)
                if ctype is not None:
                    self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802 - http.server API
                with server._lock:
                    server.requests.append(("POST", self.path))
                self.send_response(405)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):  # keep test output clean
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/source.json"

    def _resolve_asset(self, path):
        """Return `(status, body, content_type)` for a download request path.

        Called with `_lock` held. Unregistered paths are "permanently
        unavailable"; registered paths may be preceded by a configurable number
        of transient failures.
        """
        remaining = self.transient.get(path, 0)
        if remaining > 0:
            self.transient[path] = remaining - 1
            return (self.transient_status, b"transient failure", "text/plain")
        asset = self.assets.get(path)
        if asset is None:
            return (self.missing_status, b"not found", "text/plain")
        return asset

    def set_asset(self, path, body=b"payload-bytes", content_type="video/mp4",
                  status=200):
        """Register downloadable content at a request path."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        with self._lock:
            self.assets[path] = (status, body, content_type)

    def set_media(self, entry_id, fmt=None, **kwargs):
        self.set_asset(media_path(entry_id, fmt), **kwargs)

    def set_preview(self, entry_id, **kwargs):
        kwargs.setdefault("content_type", "image/jpeg")
        kwargs.setdefault("body", b"preview-bytes")
        self.set_asset(preview_path(entry_id), **kwargs)

    def serve_entry(self, entry_id, fmt=None, **kwargs):
        """Register both the media and the preview asset for an entry."""
        self.set_media(entry_id, fmt=fmt, **kwargs)
        self.set_preview(entry_id)

    def fail_transiently(self, path, times, status=503):
        """Serve `times` transient failures at `path` before succeeding."""
        with self._lock:
            self.transient[path] = times
            self.transient_status = status

    def hits(self, path):
        """Number of GET requests received for `path`."""
        with self._lock:
            return sum(1 for method, seen in self.requests
                       if method == "GET" and seen == path)

    def paths(self):
        with self._lock:
            return [seen for _method, seen in self.requests]

    def set(self, payload):
        with self._lock:
            self.payload = payload
            self.raw_body = None

    def set_raw(self, body, status=200):
        with self._lock:
            self.raw_body = body
            self.status = status

    def shutdown(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def source():
    server = SourceServer()
    try:
        yield server
    finally:
        server.shutdown()


@pytest.fixture
def run_cli(tmp_path):
    """Run `python mvault.py ...` in an isolated working directory."""

    def _run(*args, cwd=None):
        return subprocess.run(
            [sys.executable, str(MVAULT), *[str(a) for a in args]],
            cwd=str(cwd or tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )

    return _run


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


def read_catalog(workdir, name="vault"):
    return json.loads((Path(workdir) / name / "catalog.json").read_text(encoding="utf-8"))


def find_entry(catalog, entry_id, category=None):
    for cat in ((category,) if category else CATEGORIES):
        for entry in catalog[cat]:
            if entry["id"] == entry_id:
                return entry
    return None


def latest_key(history):
    """Current value key = latest datetime key, in chronological order."""
    return sorted(history)[-1]


def current(history):
    return history[latest_key(history)]


def keys_sorted(history):
    return sorted(history)


@pytest.fixture
def vault(run_cli, workdir, source):
    """An initialized vault named `vault` pointed at the local source server."""
    result = run_cli("init", "vault", source.url)
    assert result.returncode == 0, result.stderr
    return Path(workdir) / "vault"


@pytest.fixture
def helpers():
    class _H:
        make_source_entry = staticmethod(make_source_entry)
        make_payload = staticmethod(make_payload)
        read_catalog = staticmethod(read_catalog)
        find_entry = staticmethod(find_entry)
        latest_key = staticmethod(latest_key)
        current = staticmethod(current)
        keys_sorted = staticmethod(keys_sorted)
        media_path = staticmethod(media_path)
        preview_path = staticmethod(preview_path)
        media_dir = staticmethod(media_dir)
        preview_dir = staticmethod(preview_dir)
        listing = staticmethod(listing)
        make_v1_entry = staticmethod(make_v1_entry)
        make_v2_entry = staticmethod(make_v2_entry)

    return _H


def copy_tree_snapshot(path):
    """Byte-level snapshot of a directory, for `leave the vault unchanged`."""
    snap = {}
    for item in sorted(Path(path).rglob("*")):
        if item.is_file():
            snap[str(item.relative_to(path))] = item.read_bytes()
    return snap


@pytest.fixture
def snapshot():
    return copy_tree_snapshot


@pytest.fixture
def restore():
    def _restore(src, dst):
        shutil.rmtree(dst)
        shutil.copytree(src, dst)

    return _restore


# --------------------------------------------------------------------------
# legacy (version 1 / version 2) catalog helpers
#
# | `1` | Supported | Flat `entries` list; `source_id`; UNIX-epoch history
#   keys; no `removed`; no `annotations` |
# | `2` | Supported | Category arrays; full `source`; ISO 8601 history keys;
#   no `removed`; no `annotations` |
# --------------------------------------------------------------------------

V1_EPOCH = "1718444400"           # UNIX epoch seconds, as a string key
V1_EPOCH_ISO = "2024-06-15T09:40:00"  # the same instant, ISO 8601 in UTC
V1_EPOCH_LATER = "1718448000"
V1_EPOCH_LATER_ISO = "2024-06-15T10:40:00"

V2_STAMP = "2024-06-15T09:40:00"

V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{source_id}"


def make_v1_entry(entry_id, epoch=V1_EPOCH, **overrides):
    """A version 1 entry: UNIX-epoch string history keys, no removed/annotations."""
    entry = {
        "id": entry_id,
        "published": "2024-05-01T08:30:00",
        "width": 1920,
        "height": 1080,
        "title": {epoch: f"Title {entry_id}"},
        "description": {epoch: f"Description {entry_id}"},
        "views": {epoch: 100},
        "likes": {epoch: 10},
        "preview": {epoch: f"hash-{entry_id}"},
    }
    entry.update(overrides)
    return entry


def make_v1_catalog(entries=None, source_id="chan-1", **overrides):
    """| `version` | integer | `1` | + | `source_id` | + flat | `entries` |"""
    catalog = {
        "version": 1,
        "source_id": source_id,
        "entries": list(entries or []),
    }
    catalog.update(overrides)
    return catalog


def make_v2_entry(entry_id, stamp=V2_STAMP, **overrides):
    """A version 2 entry: ISO 8601 history keys, no removed/annotations."""
    entry = {
        "id": entry_id,
        "published": "2024-05-01T08:30:00",
        "width": 1920,
        "height": 1080,
        "title": {stamp: f"Title {entry_id}"},
        "description": {stamp: f"Description {entry_id}"},
        "views": {stamp: 100},
        "likes": {stamp: 10},
        "preview": {stamp: f"hash-{entry_id}"},
    }
    entry.update(overrides)
    return entry


def make_v2_catalog(source, episodes=None, streams=None, clips=None, **overrides):
    """| `version` | `2` | + full `source` + `episodes`/`streams`/`clips` arrays."""
    catalog = {
        "version": 2,
        "source": source,
        "episodes": list(episodes or []),
        "streams": list(streams or []),
        "clips": list(clips or []),
    }
    catalog.update(overrides)
    return catalog


def write_vault(workdir, catalog, name="vault", raw=None):
    """Create `<workdir>/<name>/catalog.json` holding `catalog` (or `raw` text)."""
    vault_dir = Path(workdir) / name
    vault_dir.mkdir(parents=True, exist_ok=True)
    text = raw if raw is not None else json.dumps(catalog, indent=2) + "\n"
    (vault_dir / "catalog.json").write_text(text, encoding="utf-8")
    return vault_dir


@pytest.fixture
def make_vault(workdir):
    """Materialize a vault directory from a catalog object (any version)."""

    def _make(catalog=None, name="vault", raw=None):
        return write_vault(workdir, catalog, name=name, raw=raw)

    return _make


@pytest.fixture
def legacy(source):
    """Builders for legacy catalogs, with `source` bound to the test server."""

    class _L:
        V1_EPOCH = V1_EPOCH
        V1_EPOCH_ISO = V1_EPOCH_ISO
        V1_EPOCH_LATER = V1_EPOCH_LATER
        V1_EPOCH_LATER_ISO = V1_EPOCH_LATER_ISO
        V2_STAMP = V2_STAMP
        V1_SOURCE_TEMPLATE = V1_SOURCE_TEMPLATE
        v1_entry = staticmethod(make_v1_entry)
        v1_catalog = staticmethod(make_v1_catalog)
        v2_entry = staticmethod(make_v2_entry)

        @staticmethod
        def v2_catalog(episodes=None, streams=None, clips=None, **overrides):
            return make_v2_catalog(source.url, episodes, streams, clips, **overrides)

        @staticmethod
        def v1_source(source_id):
            return V1_SOURCE_TEMPLATE.format(source_id=source_id)

    return _L


# --------------------------------------------------------------------------
# version 3 catalog helpers, for hand-built `digest` fixtures
#
# | v3 | `Episodes`, `Streams`, `Clips` | Full removal detection | ISO 8601
#   string keys |
# --------------------------------------------------------------------------

V3_STAMP_1 = "2024-06-15T09:40:00"
V3_STAMP_2 = "2024-06-16T09:40:00"
V3_STAMP_3 = "2024-06-17T09:40:00"


def make_v3_entry(entry_id, stamp=V3_STAMP_1, **overrides):
    """A version 3 entry: ISO 8601 history keys plus `removed`/`annotations`."""
    entry = make_v2_entry(entry_id, stamp=stamp)
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    entry.update(overrides)
    return entry


def make_v3_catalog(source, episodes=None, streams=None, clips=None, **overrides):
    catalog = {
        "version": 3,
        "source": source,
        "episodes": list(episodes or []),
        "streams": list(streams or []),
        "clips": list(clips or []),
    }
    catalog.update(overrides)
    return catalog


@pytest.fixture
def catalogs(source):
    """Builders for hand-written v3 catalogs bound to the test source server."""

    class _C:
        STAMP_1 = V3_STAMP_1
        STAMP_2 = V3_STAMP_2
        STAMP_3 = V3_STAMP_3
        entry = staticmethod(make_v3_entry)

        @staticmethod
        def catalog(episodes=None, streams=None, clips=None, **overrides):
            return make_v3_catalog(source.url, episodes, streams, clips, **overrides)

    return _C


def digest_lines(stdout):
    """Digest body lines (everything but the trailing metadata line)."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    return lines[:-1]


def trailing_line(stdout):
    """| Trailing line | Metadata about the digest run |"""
    lines = [line for line in stdout.splitlines() if line.strip()]
    return lines[-1]


def section(stdout, header):
    """Raw lines nested under a `header` line, up to the next same-indent line.

    Accepts either the full digest stdout or an already-extracted section, so
    a category section can be searched for its change-type groups.
    """
    lines = digest_lines(stdout) if isinstance(stdout, str) else list(stdout)
    collected = []
    depth = None
    for line in lines:
        indent = len(line) - len(line.lstrip())
        if depth is None:
            if line.strip().rstrip(":").lower() == header.rstrip(":").lower():
                depth = indent
            continue
        if indent <= depth:
            break
        collected.append(line)
    return collected


def group(stdout, category, name):
    """Entry lines of one change-type group inside one category."""
    return [line.strip() for line in section(section(stdout, category), name)]


def headers(stdout):
    """Every header line (a line ending in `:`), in order, stripped."""
    return [line.strip().rstrip(":") for line in digest_lines(stdout)
            if line.strip().endswith(":")]


@pytest.fixture
def digest():
    class _D:
        lines = staticmethod(digest_lines)
        trailing = staticmethod(trailing_line)
        section = staticmethod(section)
        group = staticmethod(group)
        headers = staticmethod(headers)

    return _D
