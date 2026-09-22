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

# Most tests drive the CLI as a subprocess; the few that mock HTTP with `responses`
# import the package directly and need the repository root importable.
sys.path.insert(0, str(REPO_ROOT))

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


#: Derivation of a full source URL from a version 1 `source_id`.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{}"

#: UNIX-epoch history key used by the v1 fixtures, and its UTC ISO 8601 form.
V1_EPOCH = "1718444400"
V1_EPOCH_ISO = "2024-06-15T09:40:00"

#: ISO 8601 history key used by the v2 fixtures.
V2_STAMP = "2024-06-15T09:40:00"


def v1_entry(entry_id, stamp=V1_EPOCH, **overrides):
    """A complete version 1 entry: nine fields, UNIX-epoch history keys."""
    entry = {
        "id": entry_id,
        "published": "2024-01-01T00:00:00",
        "width": 1920,
        "height": 1080,
        "title": {stamp: f"Title {entry_id}"},
        "description": {stamp: f"Description {entry_id}"},
        "views": {stamp: 10},
        "likes": {stamp: 2},
        "preview": {stamp: f"hash-{entry_id}"},
    }
    entry.update(overrides)
    return entry


def v1_catalog(entries=(), source_id="chan-1"):
    """A version 1 catalog: flat `entries` list and a short `source_id`."""
    return {"version": 1, "source_id": source_id, "entries": list(entries)}


def v2_entry(entry_id, stamp=V2_STAMP, **overrides):
    """A complete version 2 entry: nine fields, ISO 8601 history keys."""
    entry = {
        "id": entry_id,
        "published": "2024-01-01T00:00:00",
        "width": 1920,
        "height": 1080,
        "title": {stamp: f"Title {entry_id}"},
        "description": {stamp: f"Description {entry_id}"},
        "views": {stamp: 10},
        "likes": {stamp: 2},
        "preview": {stamp: f"hash-{entry_id}"},
    }
    entry.update(overrides)
    return entry


def v2_catalog(episodes=(), streams=(), clips=(), source="http://example.invalid/source.json"):
    """A version 2 catalog: full `source` URL and the three category arrays."""
    return {
        "version": 2,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def write_vault(tmp_path, catalog, name="vault"):
    """Create `<name>/catalog.json` by hand, bypassing `init`."""
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    body = catalog if isinstance(catalog, str) else json.dumps(catalog)
    (directory / "catalog.json").write_text(body)
    return directory


def read_backup(vault_dir):
    return json.loads((vault_dir / "catalog.bak").read_text())


def all_entries(catalog):
    """Every stored entry, across all three categories."""
    return [entry for category in ("episodes", "streams", "clips") for entry in catalog[category]]


def migrated(run, tmp_path, catalog, name="vault"):
    """Write a hand-made legacy catalog, migrate it, and return the v3 result."""
    directory = write_vault(tmp_path, catalog, name)
    result = run("migrate", name)
    assert result.returncode == 0, result.stderr
    return read_catalog(directory)
