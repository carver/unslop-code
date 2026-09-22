"""Shared fixtures: CLI invocation, a stub media source, and a running viewer."""

import http.client
import json
import re
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MVAULT = PROJECT_ROOT / "mvault.py"

# The viewer tests drive the server in-process, so the package must import
# regardless of how pytest was invoked.
sys.path.insert(0, str(PROJECT_ROOT))

from mvaultlib.server import ViewerServer  # noqa: E402


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


# --- Version 3 catalogs ------------------------------------------------------


def v3_entry(entry_id, published="2024-01-01T00:00:00", **histories):
    """A v3 entry: static fields plus six single-point histories by default."""
    entry = {
        "id": entry_id,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": {V2_KEY: f"title-{entry_id}"},
        "description": {V2_KEY: f"description-{entry_id}"},
        "views": {V2_KEY: 10},
        "likes": {V2_KEY: 5},
        "preview": {V2_KEY: f"preview-{entry_id}"},
        "removed": {V2_KEY: False},
        "annotations": [],
    }
    entry.update(histories)
    return entry


def v3_catalog(source, episodes=(), streams=(), clips=()):
    return {
        "version": 3,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


# --- Viewer ------------------------------------------------------------------

REDIRECTS = (301, 302, 303, 307, 308)


class Response:
    """One HTTP response: status line, headers and decoded body."""

    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def location(self):
        return self.headers.get("Location")

    def lines_with(self, needle):
        """The body lines containing `needle`."""
        return [line for line in self.body.splitlines() if needle in line]


class ViewerClient:
    """A minimal browser: keeps cookies, and follows redirects only on request."""

    def __init__(self, port, cookies=None):
        self.port = port
        self.cookies = dict(cookies or {})

    def get(self, path, follow=False):
        return self.request("GET", path, follow=follow)

    def post(self, path, fields=None, body=None, follow=False):
        encoded = urllib.parse.urlencode(fields) if fields is not None else body
        return self.request("POST", path, body=encoded or "", follow=follow)

    def request(self, method, path, body=None, follow=False):
        response = self.send(method, path, body)
        for _ in range(5):
            if not follow or response.status not in REDIRECTS or not response.location:
                break
            response = self.send("GET", response.location, None)
        return response

    def send(self, method, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=self.headers(body))
            raw = connection.getresponse()
            response = Response(raw.status, dict(raw.getheaders()), raw.read().decode("utf-8"))
        finally:
            connection.close()
        self.remember_cookies(response)
        return response

    def headers(self, body):
        headers = {}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        return headers

    def remember_cookies(self, response):
        """Store any `Set-Cookie` the response carries, ignoring its attributes."""
        header = response.headers.get("Set-Cookie")
        if header:
            name, _, value = header.split(";")[0].partition("=")
            self.cookies[name.strip()] = value.strip()


class RunningViewer:
    """A viewer server serving `root` on an ephemeral port, in a thread."""

    def __init__(self, root):
        self.server = ViewerServer(("127.0.0.1", 0), root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.browser = self.client()

    @property
    def port(self):
        return self.server.server_port

    def client(self, cookies=None):
        """A fresh browser: no cookies unless it is handed some."""
        return ViewerClient(self.port, cookies)

    def get(self, path, follow=False):
        return self.browser.get(path, follow=follow)

    def post(self, path, fields=None, body=None, follow=False):
        return self.browser.post(path, fields=fields, body=body, follow=follow)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def viewer(tmp_path):
    """A viewer rooted at `tmp_path`, with one cookie-keeping browser attached."""
    running = RunningViewer(tmp_path)
    yield running
    running.stop()


def place_preview(vault, name, body=b"preview bytes"):
    """Put a file into `<vault>/previews/` as if a previous sync had fetched it."""
    directory = Path(vault) / "previews"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(body)
    return directory / name


# --- Detail page chart data --------------------------------------------------

EMBEDDED_JSON = re.compile(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.S)


def chart_payload(body):
    """The machine-readable chart data a detail page embeds, parsed."""
    match = EMBEDDED_JSON.search(body)
    assert match, "the page embeds no machine-readable chart data"
    return json.loads(match.group(1))


def chart_points(body, field):
    """The embedded `(timestamp, value)` pairs of one chart field."""
    return [(point["timestamp"], point["value"]) for point in chart_payload(body).get(field, [])]
