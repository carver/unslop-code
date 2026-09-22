"""Shared fixtures: CLI invocation helper and a stub media-source HTTP server."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

MVAULT = Path(__file__).resolve().parents[1] / "mvault.py"


def run_cli(*args, cwd):
    """Run `python mvault.py <args>` in `cwd` and capture its streams."""
    return subprocess.run(
        [sys.executable, str(MVAULT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def read_catalog(vault):
    return json.loads((Path(vault) / "catalog.json").read_text())


def entry_by_id(catalog, category, entry_id):
    return next(e for e in catalog[category] if e["id"] == entry_id)


def source_entry(entry_id, published="2024-01-01T00:00:00", **overrides):
    """A source entry carrying all nine required fields."""
    entry = {
        "id": entry_id,
        "published": published,
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


def payload(episodes=(), streams=(), clips=()):
    return {
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


class Asset:
    """A downloadable media or preview file, with a scripted failure streak."""

    def __init__(self, body=b"asset-bytes", content_type="video/mp4", failures=0, status=200):
        self.body = body
        self.content_type = content_type
        self.failures = failures
        self.status = status

    def response(self):
        """The `(status, content type, body)` of one request for this asset."""
        if self.failures:
            self.failures -= 1
            return 503, "text/plain", b"try again later"
        return self.status, self.content_type, self.body


class SourceServer:
    """Serves the source document, plus any registered media/preview assets."""

    def __init__(self):
        self.status = 200
        self.body = json.dumps(payload()).encode()
        self.requests = []
        self.assets = {}

    def serve(self, data):
        """Serve `data` as a JSON document on subsequent requests."""
        self.status = 200
        self.body = json.dumps(data).encode()

    def serve_raw(self, body, status=200):
        self.status = status
        self.body = body.encode() if isinstance(body, str) else body

    def serve_asset(self, kind, name, **options):
        """Register `<...>/<kind>/<name>` as a downloadable asset."""
        self.assets[(kind, name)] = Asset(**options)

    def serve_entry(self, entry_id, fmt=None, **options):
        """Register both assets of one entry: its media and its preview."""
        media_name = entry_id if fmt is None else f"{entry_id}.{fmt}"
        self.serve_asset("media", media_name, **options)
        self.serve_asset("preview", entry_id, content_type="image/jpeg")

    def response(self, path):
        """The response for `path`: a registered asset, or the source document."""
        parts = path.strip("/").split("/")
        if len(parts) > 1 and parts[-2] in ("media", "preview"):
            asset = self.assets.get((parts[-2], parts[-1]))
            return asset.response() if asset else (404, "text/plain", b"not found")
        return self.status, "application/json", self.body

    def asset_requests(self):
        """Every request path that addressed a media or preview asset."""
        return [path for path in self.requests if "/media/" in path or "/preview/" in path]


@pytest.fixture
def source():
    """A live HTTP source; yields the controllable server with a `.url`."""
    state = SourceServer()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.requests.append(self.path)
            status, content_type, body = state.response(self.path)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{httpd.server_port}/source.json"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield state
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture
def vault(tmp_path, source):
    """An initialised vault named `demo` pointing at the stub source."""
    result = run_cli("init", "demo", source.url, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return tmp_path / "demo"


# --- Legacy (v1, v2) catalogs ------------------------------------------------

# 1718444400 is 2024-06-15T09:40:00 UTC; 1700000000 is 2023-11-14T22:13:20 UTC.
V1_KEY = "1718444400"
V1_OLDER_KEY = "1700000000"
V2_KEY = "2024-06-15T09:40:00"
V2_OLDER_KEY = "2023-11-14T22:13:20"


def legacy_entry(entry_id, key, published="2024-01-01T00:00:00", **overrides):
    """A v1/v2 entry: four static fields plus five single-point histories."""
    entry = {
        "id": entry_id,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": {key: f"title-{entry_id}"},
        "description": {key: f"description-{entry_id}"},
        "views": {key: 10},
        "likes": {key: 5},
        "preview": {key: f"preview-{entry_id}"},
    }
    entry.update(overrides)
    return entry


def v1_entry(entry_id, key=V1_KEY, **overrides):
    return legacy_entry(entry_id, key, **overrides)


def v2_entry(entry_id, key=V2_KEY, **overrides):
    return legacy_entry(entry_id, key, **overrides)


def v1_catalog(entries=(), source_id="demo-channel"):
    return {"version": 1, "source_id": source_id, "entries": list(entries)}


def v2_catalog(source, episodes=(), streams=(), clips=()):
    return {
        "version": 2,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def write_vault(tmp_path, catalog, name="demo"):
    """Create the vault directory `name` holding `catalog` verbatim."""
    directory = tmp_path / name
    directory.mkdir(exist_ok=True)
    (directory / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    return directory


def read_backup(vault):
    return json.loads((Path(vault) / "catalog.bak").read_text())


# --- Download artifacts ------------------------------------------------------


def media_names(vault):
    """The file names in `<vault>/media/`, sorted."""
    return sorted(path.name for path in (Path(vault) / "media").iterdir())


def preview_names(vault):
    """The file names in `<vault>/previews/`, sorted."""
    return sorted(path.name for path in (Path(vault) / "previews").iterdir())


def place_media(vault, name, body=b"already here"):
    """Put a file into `<vault>/media/` as if a previous sync had fetched it."""
    directory = Path(vault) / "media"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(body)
    return directory / name


def catalog_bytes(vault):
    return (Path(vault) / "catalog.json").read_bytes()
