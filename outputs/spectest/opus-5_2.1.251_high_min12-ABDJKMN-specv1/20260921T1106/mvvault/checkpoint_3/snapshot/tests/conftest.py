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
        self.feed_path = "/feed.json"
        self.routes = {}          # path -> asset description (media/preview)

    # -- download asset routing (spec: Download Sources and Targets) --------
    def serve(self, path, body=b"BODY", content_type="video/mp4", status=200,
              transient=0, fail_status=503):
        """Register an asset route.

        `transient` makes the first N requests answer `fail_status` before the
        route starts succeeding, which is how retry behavior is exercised.
        """
        route = {
            "body": body if isinstance(body, bytes) else str(body).encode(),
            "content_type": content_type,
            "status": status,
            "transient": transient,
            "fail_status": fail_status,
            "hits": 0,
        }
        self.routes[path] = route
        return route

    def media_path(self, eid, fmt=None):
        name = eid if fmt is None else "%s.%s" % (eid, fmt)
        return "%s/media/%s" % (self.feed_path, name)

    def preview_path(self, eid):
        return "%s/preview/%s" % (self.feed_path, eid)

    def media(self, eid, fmt=None, **kwargs):
        return self.serve(self.media_path(eid, fmt), **kwargs)

    def preview(self, eid, **kwargs):
        kwargs.setdefault("content_type", "image/png")
        return self.serve(self.preview_path(eid), **kwargs)

    def assets(self, *ids, fmt=None, **kwargs):
        """Serve both media and preview for every id."""
        for eid in ids:
            self.media(eid, fmt=fmt, **kwargs)
            self.preview(eid)

    def hits(self, path):
        route = self.routes.get(path)
        return 0 if route is None else route["hits"]

    def requested(self, path):
        return [item for item in self.requests if item[1] == path]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):  # keep the pytest output clean
        pass

    def _send_empty(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _respond(self):
        state = self.server.state
        state.requests.append((self.command, self.path))
        if self.path != state.feed_path:
            return self._respond_asset(state)
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

    def _respond_asset(self, state):
        """Media/preview assets; unregistered paths are permanently absent."""
        route = state.routes.get(self.path)
        if route is None:
            return self._send_empty(404)
        route["hits"] += 1
        status = route["status"]
        if route["transient"] and route["hits"] <= route["transient"]:
            status = route["fail_status"]
        if status != 200:
            return self._send_empty(status)
        body = route["body"]
        self.send_response(200)
        if route["content_type"] is not None:
            self.send_header("Content-Type", route["content_type"])
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
    state.url = "http://127.0.0.1:%d%s" % (server.server_address[1],
                                           state.feed_path)
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
    def __init__(self, body, content_type="application/octet-stream"):
        self._body = body
        self.headers = {} if content_type is None else {"Content-Type": content_type}

    def read(self):
        return self._body

    def info(self):
        return self.headers

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
            content_type = "application/octet-stream"
            if isinstance(body, tuple):          # (body, content-type)
                body, content_type = body
            if not isinstance(body, (bytes, str)):
                body = json.dumps(body)
                content_type = "application/json"
            if isinstance(body, str):
                body = body.encode("utf-8")
            return _FakeResponse(body, content_type)

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


# --------------------------------------------------------------------------
# download helpers (spec: Download Sources and Targets / Download Rules)
# --------------------------------------------------------------------------

MEDIA_DIR = "media"
PREVIEW_DIR = "previews"


def names_in(vault, subdir):
    """Sorted file names inside `<vault>/<subdir>`; empty when absent."""
    path = os.path.join(str(vault), subdir)
    if not os.path.isdir(path):
        return []
    return sorted(os.listdir(path))


def media_names(vault):
    return names_in(vault, MEDIA_DIR)


def preview_names(vault):
    return names_in(vault, PREVIEW_DIR)


def stored_ids(names):
    """Ids implied by stored file names (name up to the first dot)."""
    return [name.split(".", 1)[0] for name in names]


def place_file(vault, subdir, name, data=b"old"):
    """Drop a pre-existing file into `<vault>/<subdir>`."""
    path = os.path.join(str(vault), subdir)
    os.makedirs(path, exist_ok=True)
    full = os.path.join(path, name)
    with open(full, "wb") as fh:
        fh.write(data)
    return full


# --------------------------------------------------------------------------
# digest helpers (spec: `digest` Output Layout)
# --------------------------------------------------------------------------

def lines(text):
    return [line for line in text.splitlines() if line.strip()]


def section_of(text, heading):
    """Lines under a top-level (unindented) heading, up to the next one."""
    collected = []
    inside = False
    for line in text.splitlines():
        if not line.strip():
            continue
        unindented = line == line.lstrip()
        if unindented:
            if inside:
                break
            inside = line.strip().rstrip(":") == heading
            continue
        if inside:
            collected.append(line.strip())
    return collected


def entry_lines(text, heading, group):
    """Entry lines under `group` inside category `heading`."""
    collected = []
    inside = False
    for line in section_of(text, heading):
        stripped = line.rstrip(":")
        if stripped in ("Removals", "Additions", "Field updates"):
            inside = stripped == group
            continue
        if inside:
            collected.append(line.lstrip("-* ").strip())
    return collected
