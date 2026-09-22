"""Shared fixtures for the mvault spec suite.

Tests drive the real CLI (`python mvault.py <subcommand> ...`) in a subprocess
and serve source metadata from a local HTTP server, so the urllib.request GET
in `sync` is exercised end to end.
"""
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
