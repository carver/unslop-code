"""Shared fixtures for the mvault spec suite.

Tests drive the real CLI (`python mvault.py <subcommand> ...`) in a subprocess
and serve source metadata from a local HTTP server, so the urllib.request GET
in `sync` is exercised end to end.
"""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MVAULT = os.path.join(REPO_ROOT, "mvault.py")


class _SourceState:
    """Mutable description of what the fake media platform returns."""

    def __init__(self):
        self.payload = {"episodes": [], "streams": [], "clips": []}
        self.body = None          # raw bytes override (for malformed JSON tests)
        self.status = 200
        self.requests = []        # (method, path) of every served request


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):  # keep the pytest output clean
        pass

    def _respond(self):
        state = self.server.state
        state.requests.append((self.command, self.path))
        if state.status != 200:
            self.send_response(state.status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if state.body is not None:
            body = state.body
        else:
            body = json.dumps(state.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _respond
    do_HEAD = _respond
    do_POST = _respond


@pytest.fixture
def source():
    """A local HTTP source; `source.url` is what gets passed to `init`."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    state = _SourceState()
    server.state = state
    state.url = "http://127.0.0.1:%d/feed.json" % server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def run(tmp_path):
    """Run the CLI inside a scratch directory and capture the result."""

    def _run(*args, cwd=None):
        return subprocess.run(
            [sys.executable, MVAULT, *[str(a) for a in args]],
            cwd=str(cwd or tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )

    return _run


def dead_url():
    """A URL on a port nothing listens on (connection refused)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return "http://127.0.0.1:%d/gone.json" % port


def entry(eid, published="2024-01-01T00:00:00", width=1920, height=1080,
          title="T", description="D", views=0, likes=0, preview="p"):
    """A well-formed source entry (all nine required fields)."""
    return {
        "id": eid,
        "published": published,
        "width": width,
        "height": height,
        "title": title,
        "description": description,
        "views": views,
        "likes": likes,
        "preview": preview,
    }


def payload(episodes=(), streams=(), clips=()):
    return {
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def read_catalog(vault):
    with open(os.path.join(str(vault), "catalog.json"), encoding="utf-8") as fh:
        return json.load(fh)


def read_bytes(path):
    with open(str(path), "rb") as fh:
        return fh.read()


def find(catalog, category, eid):
    for item in catalog[category]:
        if item["id"] == eid:
            return item
    raise AssertionError("entry %r not found in %s" % (eid, category))


def latest(history):
    """Current value of a tracked field: the value at the latest datetime key."""
    return history[max(history)]


def keys_sorted(history):
    return sorted(history)


# --------------------------------------------------------------------------
# legacy-catalog helpers (spec: Supported Versions)
# --------------------------------------------------------------------------

# 1718444400 == 2024-06-15T09:40:00 UTC, 999999999 == 2001-09-09T01:46:39 UTC.
EPOCH = 1718444400
EPOCH_ISO = "2024-06-15T09:40:00"
OLD_EPOCH = 999999999
OLD_EPOCH_ISO = "2001-09-09T01:46:39"

V1_SOURCE_PREFIX = "https://media.example.com/channel/"


def v1_entry(eid, epoch=EPOCH, published="2024-01-01T00:00:00", width=1920,
             height=1080, title="T", description="D", views=5, likes=1,
             preview="p"):
    """A version 1 entry: UNIX-epoch string history keys, no removed/annotations."""
    key = str(epoch)
    return {
        "id": eid,
        "published": published,
        "width": width,
        "height": height,
        "title": {key: title},
        "description": {key: description},
        "views": {key: views},
        "likes": {key: likes},
        "preview": {key: preview},
    }


def v1_catalog(source_id="chan42", entries=()):
    return {"version": 1, "source_id": source_id, "entries": list(entries)}


def v2_entry(eid, stamp=EPOCH_ISO, published="2024-01-01T00:00:00", width=1920,
             height=1080, title="T", description="D", views=5, likes=1,
             preview="p"):
    """A version 2 entry: ISO 8601 history keys, no removed/annotations."""
    return {
        "id": eid,
        "published": published,
        "width": width,
        "height": height,
        "title": {stamp: title},
        "description": {stamp: description},
        "views": {stamp: views},
        "likes": {stamp: likes},
        "preview": {stamp: preview},
    }


def v2_catalog(source="http://example.invalid/feed.json", episodes=(),
               streams=(), clips=()):
    return {
        "version": 2,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def v3_entry(eid, stamp=EPOCH_ISO, published="2024-01-01T00:00:00", width=1920,
             height=1080, title="T", description="D", views=5, likes=1,
             preview="p", removed=False, annotations=()):
    item = v2_entry(eid, stamp, published, width, height, title, description,
                    views, likes, preview)
    item["removed"] = {stamp: removed}
    item["annotations"] = list(annotations)
    return item


def v3_catalog(source="http://example.invalid/feed.json", episodes=(),
               streams=(), clips=()):
    catalog = v2_catalog(source, episodes, streams, clips)
    catalog["version"] = 3
    return catalog


def make_vault(tmp_path, name, catalog):
    """Create `<tmp_path>/<name>/catalog.json` holding `catalog` verbatim."""
    vault = tmp_path / name
    vault.mkdir()
    write_raw(vault, json.dumps(catalog, indent=2))
    return vault


def write_raw(vault, text):
    """Write raw catalog.json text (used for malformed-JSON fixtures)."""
    path = os.path.join(str(vault), "catalog.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read_backup(vault):
    with open(os.path.join(str(vault), "catalog.bak"), encoding="utf-8") as fh:
        return json.load(fh)


def has_backup(vault):
    return os.path.exists(os.path.join(str(vault), "catalog.bak"))


class _Result:
    """Same surface as subprocess.CompletedProcess for the in-process runner."""

    def __init__(self, returncode, stdout, stderr, calls):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls = calls          # URLs passed to urllib.request.urlopen


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def close(self):
        pass


@pytest.fixture
def run_inproc(tmp_path, monkeypatch):
    """Run the CLI in-process with `urlopen` stubbed.

    Needed only where the spec fixes the source URL out of the test's control
    (the version 1 `https://media.example.com/channel/<source_id>` derivation),
    which no local HTTP server can serve.
    """
    import importlib

    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    def _run(*args, responses=None, cwd=None):
        mvault = importlib.reload(importlib.import_module("mvault"))
        calls = []

        def fake_urlopen(url, *rest, **kwargs):
            calls.append(url)
            table = responses or {}
            if url not in table:
                raise OSError("connection refused: %s" % url)
            body = table[url]
            if not isinstance(body, (bytes, str)):
                body = json.dumps(body)
            if isinstance(body, str):
                body = body.encode("utf-8")
            return _FakeResponse(body)

        monkeypatch.setattr(mvault.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.chdir(str(cwd or tmp_path))
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = mvault.main([str(a) for a in args])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return _Result(code, out.getvalue(), err.getvalue(), calls)

    return _run
