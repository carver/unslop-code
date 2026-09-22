"""Shared fixtures: CLI invocation, vault inspection, and a fake source server."""

import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MVAULT = REPO_ROOT / "mvault.py"

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def run_mvault(*args, cwd):
    """Run `python mvault.py <args...>` in `cwd` and return the CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(MVAULT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture
def run(tmp_path):
    """Invoke the CLI inside an isolated temp directory."""

    def _run(*args, cwd=None):
        return run_mvault(*args, cwd=cwd or tmp_path)

    return _run


class SourceServer:
    """Localhost HTTP server whose JSON body and status are swappable per test."""

    def __init__(self):
        self.status = 200
        self.body = json.dumps({"episodes": [], "streams": [], "clips": []})
        self.content_type = "application/json"
        self.request_count = 0
        self.methods = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/source.json"

    def serve(self, payload):
        """Serve `payload` (a Python object) as a 200 JSON response."""
        self.status = 200
        self.body = json.dumps(payload)

    def serve_raw(self, text, status=200, content_type="application/json"):
        """Serve arbitrary text, for malformed-body and error-status cases."""
        self.status = status
        self.body = text
        self.content_type = content_type

    def shutdown(self):
        self._server.shutdown()
        self._server.server_close()

    def _handler_class(server_self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                server_self.request_count += 1
                server_self.methods.append(self.command)
                payload = server_self.body.encode()
                self.send_response(server_self.status)
                self.send_header("Content-Type", server_self.content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                """Silence the default stderr access log."""

        return Handler


@pytest.fixture
def source():
    server = SourceServer()
    yield server
    server.shutdown()


@pytest.fixture
def dead_url():
    """A URL on a closed port, for transport-failure cases."""
    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_address[1]
    probe.server_close()
    return f"http://127.0.0.1:{port}/source.json"


def source_entry(entry_id, **overrides):
    """A complete nine-field source entry, with per-test overrides."""
    entry = {
        "id": entry_id,
        "published": "2024-01-01T00:00:00",
        "width": 1920,
        "height": 1080,
        "title": f"Title {entry_id}",
        "description": f"Description {entry_id}",
        "views": 10,
        "likes": 2,
        "preview": f"hash-{entry_id}",
    }
    entry.update(overrides)
    return entry


def payload(episodes=(), streams=(), clips=()):
    """A well-formed source response body."""
    return {
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


@pytest.fixture
def vault(tmp_path, source, run):
    """An initialized vault named `vault` pointed at the fake source server."""
    result = run("init", "vault", source.url)
    assert result.returncode == 0, result.stderr
    return tmp_path / "vault"


def read_catalog(vault_dir):
    return json.loads((vault_dir / "catalog.json").read_text())


def find_entry(catalog, category, entry_id):
    """Return the single entry with `entry_id` in `category`, or None."""
    matches = [e for e in catalog[category] if e["id"] == entry_id]
    assert len(matches) <= 1, f"duplicate id {entry_id} in {category}"
    return matches[0] if matches else None


def latest(history):
    """Current value of a tracked field: the value at the newest timestamp key."""
    return history[max(history)]


def timestamps(history):
    """History keys in chronological order."""
    return sorted(history)
