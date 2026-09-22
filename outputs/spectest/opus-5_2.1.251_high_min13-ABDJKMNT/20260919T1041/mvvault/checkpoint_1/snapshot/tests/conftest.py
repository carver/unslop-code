"""Shared fixtures: a real CLI runner and a local HTTP source server."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

MVAULT = Path(__file__).resolve().parent.parent / "mvault.py"


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


class SourceServer:
    """Serves whatever `payload` (or raw `body`) the test last assigned."""

    def __init__(self):
        self.payload = {"episodes": [], "streams": [], "clips": []}
        self.body = None
        self.status = 200
        self.requests = 0
        self.url = None

    def rendered(self):
        self.requests += 1
        if self.body is not None:
            return self.body.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


@pytest.fixture
def source():
    state = SourceServer()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = state.rendered()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}/feed.json"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def source_entry(entry_id, published="2024-01-01T00:00:00", **overrides):
    """A source row carrying all nine required fields."""
    entry = {
        "id": entry_id,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": f"title-{entry_id}",
        "description": f"description-{entry_id}",
        "views": 10,
        "likes": 2,
        "preview": f"hash-{entry_id}",
    }
    entry.update(overrides)
    return entry


def read_catalog(vault_dir):
    return json.loads((Path(vault_dir) / "catalog.json").read_text())


def current(history):
    """Value at the latest datetime key of a tracked-field history object."""
    return history[max(history)]


@pytest.fixture
def vault(tmp_path, run_cli, source):
    """An initialized vault named 'v' pointed at the local source server."""
    result = run_cli("init", "v", source.url)
    assert result.returncode == 0, result.stderr
    return tmp_path / "v"
