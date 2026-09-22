"""Shared fixtures for the mvault spec tests.

Everything is exercised through the CLI surface required by the spec:
    python mvault.py <subcommand> [args...]
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MVAULT = os.path.join(REPO_ROOT, "mvault.py")


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
    """Invoke `python mvault.py ...` inside an isolated working directory."""

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


class _Source:
    """A tiny HTTP source whose payload can be swapped between syncs."""

    def __init__(self):
        self.body = b"{}"
        self.status = 200
        self.content_type = "application/json"
        self.requests = []
        self.delay = 0.0

    def set_payload(self, obj):
        self.body = json.dumps(obj).encode("utf-8")

    def set_raw(self, data, status=200, content_type="application/json"):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.body = data
        self.status = status
        self.content_type = content_type


@pytest.fixture
def source():
    """Serve mutable JSON over HTTP; `source.url` is the vault source URL."""
    state = _Source()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.requests.append(("GET", self.path))
            self.send_response(state.status)
            self.send_header("Content-Type", state.content_type)
            self.send_header("Content-Length", str(len(state.body)))
            self.end_headers()
            self.wfile.write(state.body)

        def do_POST(self):  # recorded so tests can assert GET was used
            state.requests.append(("POST", self.path))
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):  # silence stderr logging
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = "http://127.0.0.1:%d/source.json" % server.server_address[1]
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def entry(eid, published="2024-01-01T00:00:00", **over):
    """A well-formed source entry with all nine required fields."""
    data = {
        "id": eid,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": "Title %s" % eid,
        "description": "Description %s" % eid,
        "views": 100,
        "likes": 10,
        "preview": "hash-%s" % eid,
    }
    data.update(over)
    return data


def payload(episodes=(), streams=(), clips=()):
    return {
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def read_catalog(tmp_path, name="vault"):
    with open(os.path.join(str(tmp_path), name, "catalog.json")) as fh:
        return json.load(fh)


def find(catalog, eid, category="episodes"):
    for item in catalog[category]:
        if item["id"] == eid:
            return item
    return None


def history_keys(entry_obj, field):
    """History keys in chronological order."""
    return sorted(entry_obj[field].keys())


def current(entry_obj, field):
    """Current value = value at the latest datetime key."""
    hist = entry_obj[field]
    return hist[max(hist.keys(), key=lambda k: k)]


@pytest.fixture
def vault(run, source, tmp_path):
    """An initialized vault named `vault` pointed at the HTTP source."""
    result = run("init", "vault", source.url)
    assert result.returncode == 0, result
    return tmp_path / "vault"
