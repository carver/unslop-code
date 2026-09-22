"""Fixtures for the mvault CLI tests.

The CLI is exercised as a subprocess (`python mvault.py ...`) against a real
local HTTP server, so the tests only depend on the behaviour the spec
describes: an HTTP `GET` to the vault `source` URL returning JSON.
"""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

MVAULT = Path(__file__).resolve().parents[1] / "mvault.py"


class SourceState:
    """Mutable payload served by the source fixture."""

    def __init__(self, url):
        self.url = url
        self.payload = {"episodes": [], "streams": [], "clips": []}
        self.raw_body = None
        self.status = 200
        self.requests = 0

    def serve(self, **categories):
        """Replace the served payload, defaulting unmentioned categories."""
        self.payload = {
            "episodes": categories.get("episodes", []),
            "streams": categories.get("streams", []),
            "clips": categories.get("clips", []),
        }

    def body(self):
        if self.raw_body is not None:
            return self.raw_body
        return json.dumps(self.payload).encode()


class _SourceHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        state = self.server.state
        state.requests += 1
        body = state.body()
        self.send_response(state.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Silence the default stderr access log."""


@pytest.fixture
def source():
    """Run a local HTTP source and yield its mutable state."""
    server = HTTPServer(("127.0.0.1", 0), _SourceHandler)
    state = SourceState(f"http://127.0.0.1:{server.server_port}/feed.json")
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def run_cli(tmp_path):
    """Invoke `python mvault.py ...` inside the test's temporary directory."""

    def run(*args, cwd=None):
        return subprocess.run(
            [sys.executable, str(MVAULT), *args],
            cwd=str(cwd or tmp_path),
            capture_output=True,
            text=True,
        )

    return run


@pytest.fixture
def vault(tmp_path, run_cli, source):
    """An initialised vault pointed at the local source server."""
    result = run_cli("init", "demo", source.url)
    assert result.returncode == 0, result.stderr
    return tmp_path / "demo"


def source_entry(entry_id, **overrides):
    """Build a well-formed source entry with all nine required fields."""
    entry = {
        "id": entry_id,
        "published": "2024-01-01T00:00:00",
        "width": 1920,
        "height": 1080,
        "title": f"title-{entry_id}",
        "description": f"description-{entry_id}",
        "views": 10,
        "likes": 5,
        "preview": f"preview-{entry_id}",
    }
    entry.update(overrides)
    return entry


def read_catalog(vault_path):
    return json.loads((vault_path / "catalog.json").read_text())


def find_entry(catalog, category, entry_id):
    matches = [entry for entry in catalog[category] if entry["id"] == entry_id]
    assert len(matches) == 1, f"expected one {entry_id} in {category}, got {matches}"
    return matches[0]


def history_order(history):
    """History keys in chronological order."""
    return sorted(history)


def current(history):
    """Value at the latest datetime key."""
    return history[history_order(history)[-1]]
