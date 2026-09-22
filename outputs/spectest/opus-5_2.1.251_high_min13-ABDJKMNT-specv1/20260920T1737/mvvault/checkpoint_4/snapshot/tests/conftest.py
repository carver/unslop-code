"""Fixtures for the mvault CLI tests.

The CLI is exercised as a subprocess (`python mvault.py ...`) against a real
local HTTP server, so the tests only depend on the behaviour the spec
describes: an HTTP `GET` to the vault `source` URL returning JSON.
"""

import contextlib
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

MVAULT = Path(__file__).resolve().parents[1] / "mvault.py"

# The few tests that call into the library directly import it from the repo root.
sys.path.insert(0, str(MVAULT.parent))


class SourceState:
    """Mutable payload served by the source fixture."""

    def __init__(self, url):
        self.url = url
        self.payload = {"episodes": [], "streams": [], "clips": []}
        self.raw_body = None
        self.status = 200
        self.requests = 0
        #: Download-phase controls, keyed by request tail ("media/e1", "preview/e1").
        self.asset_status = {}
        self.transient_failures = Counter()
        self.asset_requests = Counter()
        self.media_content_type = "video/mp4"
        self.preview_content_type = "image/jpeg"

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


def asset_tail(path):
    """The `<kind>/<name>` tail of a download path, or None for a metadata path."""
    for kind in ("media", "preview"):
        marker = f"/{kind}/"
        if marker in path:
            return kind, f"{kind}/{path.split(marker, 1)[1]}"
    return None, None


class _SourceHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        kind, tail = asset_tail(self.path)
        if tail is None:
            self._respond_metadata()
        else:
            self._respond_asset(kind, tail)

    def _respond_metadata(self):
        state = self.server.state
        state.requests += 1
        self._send(state.status, "application/json", state.body())

    def _respond_asset(self, kind, tail):
        state = self.server.state
        state.asset_requests[tail] += 1
        status = state.asset_status.get(tail)
        if state.transient_failures[tail] > 0:
            state.transient_failures[tail] -= 1
            status = 503
        if status is not None:
            self.send_error(status)
            return
        content_type = state.media_content_type if kind == "media" else state.preview_content_type
        self._send(200, content_type, f"{tail}-bytes".encode())

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
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


#: A UNIX-epoch history key used by the version 1 fixtures, and its ISO 8601 form.
EPOCH_KEY = "1718444400"
EPOCH_KEY_AS_ISO = "2024-06-15T09:40:00"

#: An ISO 8601 history key used by the version 2 fixtures.
ISO_KEY = "2024-06-15T09:40:00"


def legacy_entry(entry_id, key, **overrides):
    """A v1/v2 entry: the four static fields plus five single-keyed histories."""
    entry = {
        "id": entry_id,
        "published": "2024-01-01T00:00:00",
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


def v1_catalog(*entries, source_id="chan42"):
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


def write_vault(tmp_path, name, catalog):
    """Create `<name>/catalog.json` holding `catalog`, a dict or raw JSON text."""
    vault_path = tmp_path / name
    vault_path.mkdir()
    body = catalog if isinstance(catalog, str) else json.dumps(catalog, indent=2)
    (vault_path / "catalog.json").write_text(body)
    return vault_path


def v3_entry(entry_id, removed=None, **histories):
    """A v3 entry whose tracked fields carry the supplied multi-key histories."""
    entry = legacy_entry(entry_id, ISO_KEY)
    entry.update(histories)
    entry["removed"] = removed if removed is not None else {ISO_KEY: False}
    entry["annotations"] = []
    return entry


def v3_catalog(source, episodes=(), streams=(), clips=()):
    """A version 3 catalog: `source`, the three category arrays and `version`."""
    return {
        "version": 3,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def names_in(directory):
    """Sorted file names in `directory`, or an empty list when it is absent."""
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.iterdir())


#: The bind address `serve` uses when neither `--host` nor `--port` is given.
DEFAULT_VIEWER_HOST = "127.0.0.1"
DEFAULT_VIEWER_PORT = 8840

#: Seconds the viewer fixtures wait for the server, or for a browser launch.
VIEWER_TIMEOUT = 15


def free_port():
    """A port number that is free right now, for a viewer under test."""
    with contextlib.closing(socket.socket()) as probe:
        probe.bind((DEFAULT_VIEWER_HOST, 0))
        return probe.getsockname()[1]


class Response:
    """One viewer response: its status, its `Location` and its decoded body."""

    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def location(self):
        return self.headers.get("Location")

    def lines_containing(self, needle):
        return [line for line in self.body.splitlines() if needle in line]


class ViewerClient:
    """A browser-like HTTP client that never follows redirects on its own."""

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=VIEWER_TIMEOUT)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return Response(response.status, dict(response.getheaders()), response.read().decode("utf-8"))
        finally:
            connection.close()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, fields):
        """POST a form-encoded body, the way the landing page form does."""
        body = urllib.parse.urlencode(fields)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        return self.request("POST", path, body, headers)

    def follow(self, path, limit=5):
        """Fetch `path`, following redirects, and return the final response."""
        response = self.get(path)
        for _ in range(limit):
            if response.location is None:
                return response
            response = self.get(response.location)
        raise AssertionError(f"redirect loop starting at {path}")


class ViewerProcess:
    """A running `python mvault.py serve` subprocess and a client for it."""

    def __init__(self, process, client, log_path):
        self.process = process
        self.client = client
        self.log_path = log_path

    def output(self):
        return self.log_path.read_text()

    def wait_until_ready(self):
        """Block until the server accepts connections, or fail with its output."""
        deadline = time.monotonic() + VIEWER_TIMEOUT
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(f"serve exited early:\n{self.output()}")
            with contextlib.closing(socket.socket()) as probe:
                if probe.connect_ex((self.client.host, self.client.port)) == 0:
                    return
            time.sleep(0.05)
        raise AssertionError(f"serve never accepted connections:\n{self.output()}")

    def stop(self):
        """Terminate this server by its own PID and wait for it to exit."""
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=VIEWER_TIMEOUT)


@pytest.fixture
def serve_viewer(tmp_path):
    """Factory running `python mvault.py serve ...` in the test directory.

    `host` and `port` say where the returned client should connect, which is
    the default bind address unless the test passes `--host`/`--port` itself.
    """
    started = []

    def start(*args, host=DEFAULT_VIEWER_HOST, port=DEFAULT_VIEWER_PORT, env=None, cwd=None):
        log_path = tmp_path / f"serve-{len(started)}.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, str(MVAULT), "serve", *args],
                cwd=str(cwd or tmp_path),
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, **(env or {})},
            )
        viewer = ViewerProcess(process, ViewerClient(host, port), log_path)
        started.append(viewer)
        viewer.wait_until_ready()
        return viewer

    yield start
    for viewer in started:
        viewer.stop()


@pytest.fixture
def viewer(serve_viewer):
    """A viewer serving the test directory on a free port, opened at `/`."""
    port = free_port()
    return serve_viewer(f"--port={port}", port=port)


def browser_recorder(tmp_path):
    """A `BROWSER` command recording the URL it is opened with, and that file."""
    script = tmp_path / "record_browser.py"
    record = tmp_path / "browser-url.txt"
    script.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(record)!r}).write_text(sys.argv[1])\n"
    )
    return f"{sys.executable} {script} %s", record


def opened_url(record):
    """The URL the recorded browser was opened with, waiting for the launch."""
    deadline = time.monotonic() + VIEWER_TIMEOUT
    while time.monotonic() < deadline:
        if record.is_file():
            return record.read_text()
        time.sleep(0.05)
    raise AssertionError("the browser was never opened")


def write_media(vault_path, *filenames):
    """Create `<vault>/media/<filename>` for each name, marking it downloaded."""
    media = vault_path / "media"
    media.mkdir(exist_ok=True)
    for filename in filenames:
        (media / filename).write_bytes(b"media-bytes")
    return media


#: Statuses the spec allows for a viewer redirect.
REDIRECT_STATUSES = (302, 303)
