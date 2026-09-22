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
