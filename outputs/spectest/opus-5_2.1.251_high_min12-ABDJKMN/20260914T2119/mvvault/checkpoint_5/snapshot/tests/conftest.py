"""Shared fixtures/helpers for the mvault spec suite.

Everything here drives the CLI as a black box:
    python mvault.py <subcommand> [args...]
and serves the vault `source` URL from a real local HTTP server.
"""
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MVAULT = os.path.join(REPO_ROOT, "mvault.py")

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
TRACKED_FIELDS = ("title", "description", "views", "likes", "preview", "removed")
CATEGORIES = ("episodes", "streams", "clips")


# --------------------------------------------------------------------------
# CLI driver
# --------------------------------------------------------------------------
class Result:
    def __init__(self, proc):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Result(rc=%r, stdout=%r, stderr=%r)" % (
            self.returncode,
            self.stdout,
            self.stderr,
        )


@pytest.fixture
def run(tmp_path):
    """Run `python mvault.py ...` inside an isolated cwd."""

    def _run(*args, cwd=None):
        proc = subprocess.run(
            [sys.executable, MVAULT, *[str(a) for a in args]],
            cwd=str(cwd or tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return Result(proc)

    return _run


# --------------------------------------------------------------------------
# Source server
# --------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        state = self.server.state
        state.requests.append(("GET", self.path))
        asset = state.asset_response(self.path)
        if asset is not None:
            status, content_type, body = asset
            self.send_response(status)
            if content_type is not None:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        status, body = state.response()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # recorded so tests can assert GET was used
        state = self.server.state
        state.requests.append(("POST", self.path))
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):  # keep the test output clean (no pipes)
        pass


class SourceState:
    def __init__(self):
        self.payload = {"episodes": [], "streams": [], "clips": []}
        self.raw = None          # override the body with exact bytes
        self.status = 200
        self.requests = []
        # Download assets: path -> scripted list of (status, content_type,
        # body); the final response repeats once the script is exhausted.
        self.assets = {}
        self.asset_hits = {}

    def asset_response(self, path):
        """Serve `<source>/media/...` and `<source>/preview/...` requests.

        Returns None for anything that is not an asset path, so the metadata
        payload keeps being served from every other path.
        """
        if "/media/" not in path and "/preview/" not in path:
            return None
        seen = self.asset_hits.get(path, 0)
        self.asset_hits[path] = seen + 1
        script = self.assets.get(path)
        if not script:
            return (404, "text/plain", b"not found")
        return script[min(seen, len(script) - 1)]

    def response(self):
        if self.raw is not None:
            body = self.raw if isinstance(self.raw, bytes) else self.raw.encode()
        else:
            body = json.dumps(self.payload).encode()
        return self.status, body


class SourceServer:
    def __init__(self):
        self.state = SourceState()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.state = self.state
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        host, port = self._httpd.server_address[:2]
        return "http://%s:%d/source.json" % (host, port)

    def serve(self, episodes=(), streams=(), clips=()):
        self.state.raw = None
        self.state.status = 200
        self.state.payload = {
            "episodes": list(episodes),
            "streams": list(streams),
            "clips": list(clips),
        }

    def serve_object(self, obj):
        """Serve an arbitrary JSON-serialisable top-level object."""
        self.state.raw = None
        self.state.status = 200
        self.state.payload = obj

    def serve_raw(self, body, status=200):
        self.state.raw = body
        self.state.status = status

    def fail(self, status=500):
        self.state.status = status
        self.state.raw = b"boom"

    # ---- download assets ------------------------------------------------
    def asset_path(self, kind, entry_id, ext=None):
        """The server path `<source>/<kind>/<entry_id>[.<ext>]` resolves to."""
        base = urlsplit(self.url).path
        name = entry_id if ext is None else "%s.%s" % (entry_id, ext)
        return "%s/%s/%s" % (base.rstrip("/"), kind, name)

    def serve_asset(self, kind, entry_id, body=b"BYTES",
                    content_type="application/octet-stream", ext=None):
        self.state.assets[self.asset_path(kind, entry_id, ext)] = [
            (200, content_type, body)]

    def serve_media(self, entry_id, body=b"MEDIABYTES",
                    content_type="video/mp4", ext=None):
        self.serve_asset("media", entry_id, body, content_type, ext)

    def serve_preview(self, entry_id, body=b"PREVIEWBYTES",
                      content_type="image/jpeg", ext=None):
        self.serve_asset("preview", entry_id, body, content_type, ext)

    def serve_entry_assets(self, entry_id, media_type="video/mp4",
                           preview_type="image/jpeg", ext=None):
        self.serve_media(entry_id, content_type=media_type, ext=ext)
        self.serve_preview(entry_id, content_type=preview_type)

    def fail_asset(self, kind, entry_id, status=404, ext=None):
        self.state.assets[self.asset_path(kind, entry_id, ext)] = [
            (status, "text/plain", b"error")]

    def flaky_asset(self, kind, entry_id, failures=2, status=503,
                    body=b"MEDIABYTES", content_type="video/mp4", ext=None):
        """Fail `failures` times, then succeed on every later attempt."""
        script = [(status, "text/plain", b"error")] * failures
        script.append((200, content_type, body))
        self.state.assets[self.asset_path(kind, entry_id, ext)] = script

    def hits(self, kind, entry_id, ext=None):
        """How many requests reached `<source>/<kind>/<entry_id>`."""
        return self.state.asset_hits.get(self.asset_path(kind, entry_id, ext), 0)

    def asset_requests(self, kind):
        """Requested paths for one asset kind, in arrival order."""
        needle = "/%s/" % kind
        return [path for method, path in self.state.requests if needle in path]

    @property
    def requests(self):
        return self.state.requests

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def source():
    srv = SourceServer()
    try:
        yield srv
    finally:
        srv.close()


# --------------------------------------------------------------------------
# Data builders / readers
# --------------------------------------------------------------------------
def make_entry(id="e1", published="2024-05-01T12:00:00", width=1920, height=1080,
               title="Title", description="Desc", views=10, likes=1,
               preview="hash0"):
    """A source entry carrying all nine required fields."""
    return {
        "id": id,
        "published": published,
        "width": width,
        "height": height,
        "title": title,
        "description": description,
        "views": views,
        "likes": likes,
        "preview": preview,
    }


@pytest.fixture
def entry():
    return make_entry


def read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def catalog_path(root, name="vault"):
    return os.path.join(str(root), name, "catalog.json")


def backup_path(root, name="vault"):
    return os.path.join(str(root), name, "catalog.bak")


def read_catalog(root, name="vault"):
    return read_json(catalog_path(root, name))


def find_entry(catalog, category, entry_id):
    for item in catalog[category]:
        if item.get("id") == entry_id:
            return item
    return None


def parse_ts(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")


def sorted_keys(history):
    """History keys in chronological order."""
    return sorted(history, key=parse_ts)


def current(history):
    """Current value of a tracked field = value at the latest datetime key."""
    return history[sorted_keys(history)[-1]]


def all_keys(catalog):
    keys = []
    for category in CATEGORIES:
        for item in catalog[category]:
            for field in TRACKED_FIELDS:
                keys.extend(item.get(field, {}).keys())
    return keys


@pytest.fixture
def vault(run, source, tmp_path):
    """An initialised vault named `vault` pointed at the local source server."""
    res = run("init", "vault", source.url)
    assert res.returncode == 0, res
    return tmp_path / "vault"


# --------------------------------------------------------------------------
# Legacy catalog builders (versions 1 and 2)
# --------------------------------------------------------------------------
V1_SOURCE_PREFIX = "https://media.example.com/channel/"

# 1718444400 == 2024-06-15T09:40:00 UTC, 1718530800 == 2024-06-16T09:40:00 UTC.
EPOCH_A = "1718444400"
EPOCH_B = "1718530800"
ISO_A = "2024-06-15T09:40:00"
ISO_B = "2024-06-16T09:40:00"


def make_v1_entry(id="e1", published="2024-05-01T12:00:00", width=1920,
                  height=1080, title=None, description=None, views=None,
                  likes=None, preview=None):
    """A version 1 entry: nine fields, UNIX-epoch string history keys."""
    return {
        "id": id,
        "published": published,
        "width": width,
        "height": height,
        "title": {EPOCH_A: "Title"} if title is None else title,
        "description": {EPOCH_A: "Desc"} if description is None else description,
        "views": {EPOCH_A: 10} if views is None else views,
        "likes": {EPOCH_A: 1} if likes is None else likes,
        "preview": {EPOCH_A: "hash0"} if preview is None else preview,
    }


def make_v2_entry(id="e1", published="2024-05-01T12:00:00", width=1920,
                  height=1080, title=None, description=None, views=None,
                  likes=None, preview=None):
    """A version 2 entry: nine fields, ISO 8601 string history keys."""
    return {
        "id": id,
        "published": published,
        "width": width,
        "height": height,
        "title": {ISO_A: "Title"} if title is None else title,
        "description": {ISO_A: "Desc"} if description is None else description,
        "views": {ISO_A: 10} if views is None else views,
        "likes": {ISO_A: 1} if likes is None else likes,
        "preview": {ISO_A: "hash0"} if preview is None else preview,
    }


def make_v1_catalog(source_id="chan42", entries=None):
    """A version 1 catalog: flat `entries` list, `source_id`, no categories."""
    return {
        "version": 1,
        "source_id": source_id,
        "entries": [make_v1_entry()] if entries is None else list(entries),
    }


def make_v2_catalog(source="https://media.example.com/channel/chan42",
                    episodes=None, streams=(), clips=()):
    """A version 2 catalog: category arrays and a full `source` URL."""
    return {
        "version": 2,
        "source": source,
        "episodes": [make_v2_entry()] if episodes is None else list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def make_v3_catalog(source="https://media.example.com/channel/chan42",
                    episodes=(), streams=(), clips=()):
    """A native (version 3) catalog."""
    return {
        "version": 3,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def make_v3_entry(id="e1", published="2024-05-01T12:00:00", width=1920,
                  height=1080, stamp=ISO_A):
    """A native entry, including the v3-only `removed` and `annotations`."""
    return {
        "id": id,
        "published": published,
        "width": width,
        "height": height,
        "title": {stamp: "Title"},
        "description": {stamp: "Desc"},
        "views": {stamp: 10},
        "likes": {stamp: 1},
        "preview": {stamp: "hash0"},
        "removed": {stamp: False},
        "annotations": [],
    }


@pytest.fixture
def make_vault(tmp_path):
    """Create a vault directory holding a hand-written `catalog.json`."""

    def _make(catalog, name="vault"):
        directory = tmp_path / name
        directory.mkdir(parents=True, exist_ok=True)
        with open(str(directory / "catalog.json"), "w", encoding="utf-8") as fh:
            json.dump(catalog, fh, indent=2)
        return directory

    return _make


@pytest.fixture
def make_raw_vault(tmp_path):
    """Create a vault directory whose `catalog.json` holds exact text."""

    def _make(text, name="vault"):
        directory = tmp_path / name
        directory.mkdir(parents=True, exist_ok=True)
        with open(str(directory / "catalog.json"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return directory

    return _make


def catalog_bytes(root, name="vault"):
    with open(catalog_path(root, name), "rb") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# Download target helpers
# --------------------------------------------------------------------------
def media_dir(root, name="vault"):
    return os.path.join(str(root), name, "media")


def preview_dir(root, name="vault"):
    return os.path.join(str(root), name, "previews")


def listing(path):
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


def media_files(root, name="vault"):
    return listing(media_dir(root, name))


def preview_files(root, name="vault"):
    return listing(preview_dir(root, name))


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# Viewer (`serve`) fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def serve(tmp_path):
    """Start `mvault.py serve` subprocesses; each is stopped by PID at teardown."""
    import viewer_helpers

    started = []

    def _serve(name=None, host=None, port=None, cwd=None, **kwargs):
        if port is None and "use_default_port" not in kwargs:
            port = viewer_helpers.free_port()
        kwargs.pop("use_default_port", None)
        server = viewer_helpers.start_server(cwd or tmp_path, name=name,
                                             host=host, port=port, **kwargs)
        started.append(server)
        return server

    try:
        yield _serve
    finally:
        for server in started:
            server.stop()


@pytest.fixture
def save_asset(tmp_path):
    """Write a downloaded asset into `<vault>/media/` or `<vault>/previews/`."""

    def _save(kind, filename, name="vault", body=b"BYTES"):
        directory = tmp_path / name / kind
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        with open(str(path), "wb") as fh:
            fh.write(body)
        return path

    return _save
