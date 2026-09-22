"""Shared fixtures: a real CLI runner and a local HTTP source server."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

MVAULT = Path(__file__).resolve().parent.parent / "mvault.py"

#: Tests that exercise the library directly import it from the project root.
sys.path.insert(0, str(MVAULT.parent))


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


#: Path of the metadata feed; media and preview assets hang below it.
FEED_PATH = "/feed.json"


class SourceServer:
    """Serves the metadata feed plus the media and preview assets below it.

    The feed answers with `payload` (or the raw `body`) and `status`. Every
    other path is an asset: `assets` holds per-path `(status, content type,
    body)` answers, `transient` counts how many `503` responses a path emits
    before it starts succeeding, and anything else gets the asset defaults.
    """

    def __init__(self):
        self.payload = {"episodes": [], "streams": [], "clips": []}
        self.body = None
        self.status = 200
        self.requests = 0
        self.url = None
        self.asset = (200, "video/mp4", b"media-bytes")
        self.assets = {}
        self.transient = {}
        self.asset_requests = []

    def respond(self, path):
        """The `(status, content type, body)` triple to answer `path` with."""
        if path == FEED_PATH:
            return self.status, "application/json", self.rendered()
        self.asset_requests.append(path)
        if self.transient.get(path):
            self.transient[path] -= 1
            return 503, "text/plain", b"try again"
        return self.assets.get(path, self.asset)

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
            status, content_type, body = state.respond(self.path)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}{FEED_PATH}"
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


#: A version 1 `source_id` and the source URL it is defined to derive.
V1_SOURCE_ID = "chan-7"
V1_SOURCE_URL = "https://media.example.com/channel/chan-7"

#: A UNIX-epoch history key and its UTC datetime text.
EPOCH_KEY = "1718444400"
EPOCH_KEY_ISO = "2024-06-15T09:40:00"

ISO_KEY = "2024-06-15T09:40:00"


def legacy_entry(entry_id, stamp, published="2024-01-01T00:00:00", **overrides):
    """A v1/v2 entry: static fields plus the five source-tracked histories."""
    entry = {
        "id": entry_id,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": {stamp: f"title-{entry_id}"},
        "description": {stamp: f"description-{entry_id}"},
        "views": {stamp: 10},
        "likes": {stamp: 2},
        "preview": {stamp: f"hash-{entry_id}"},
    }
    entry.update(overrides)
    return entry


def v1_entry(entry_id, stamp=EPOCH_KEY, **overrides):
    """A version 1 entry, keyed by UNIX-epoch seconds."""
    return legacy_entry(entry_id, stamp, **overrides)


def v2_entry(entry_id, stamp=ISO_KEY, **overrides):
    """A version 2 entry, keyed by ISO 8601 datetimes."""
    return legacy_entry(entry_id, stamp, **overrides)


def v1_catalog(entries=(), source_id=V1_SOURCE_ID):
    """A version 1 catalog: `source_id` plus one flat `entries` list."""
    return {"version": 1, "source_id": source_id, "entries": list(entries)}


def v2_catalog(source, episodes=(), streams=(), clips=()):
    """A version 2 catalog: full `source` plus the three category arrays."""
    return {
        "version": 2,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


@pytest.fixture
def make_vault(tmp_path):
    """Write a catalog straight to disk, bypassing `init`."""

    def make(catalog, name="v"):
        vault = tmp_path / name
        vault.mkdir(exist_ok=True)
        text = catalog if isinstance(catalog, str) else json.dumps(catalog, indent=2) + "\n"
        (vault / "catalog.json").write_text(text, encoding="utf-8")
        return vault

    return make


def v3_entry(entry_id, stamp=ISO_KEY, **overrides):
    """A version 3 entry: the legacy histories plus `removed` and `annotations`."""
    entry = legacy_entry(entry_id, stamp)
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    entry.update(overrides)
    return entry


def v3_catalog(source, episodes=(), streams=(), clips=()):
    """A version 3 catalog: the version 2 layout at the native version."""
    return {**v2_catalog(source, episodes, streams, clips), "version": 3}


def stored_names(directory):
    """Sorted file names inside `directory`, or `[]` when it does not exist."""
    return sorted(path.name for path in Path(directory).iterdir()) if Path(directory).is_dir() else []
