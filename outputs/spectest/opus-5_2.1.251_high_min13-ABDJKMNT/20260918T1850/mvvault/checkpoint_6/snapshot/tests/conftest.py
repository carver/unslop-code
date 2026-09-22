"""Shared fixtures: CLI invocation, vault inspection, and a fake source server."""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
MVAULT = REPO_ROOT / "mvault.py"

# Most tests drive the CLI as a subprocess; the few that mock HTTP with `responses`
# import the package directly and need the repository root importable.
sys.path.insert(0, str(REPO_ROOT))

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

METADATA_PATH = "/source.json"


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
    """Localhost HTTP server serving vault metadata plus media/preview assets.

    The metadata document lives at `/source.json`; downloadable assets are
    registered under the paths `sync` derives from it (`/source.json/media/<id>`
    and `/source.json/preview/<id>`). Anything unregistered answers 404, which is
    the permanent-failure case; `fail_next` scripts transient failures.
    """

    def __init__(self):
        self.status = 200
        self.body = json.dumps({"episodes": [], "streams": [], "clips": []})
        self.content_type = "application/json"
        self.methods = []
        self.requests = []
        self.assets = {}
        self.pending_failures = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{METADATA_PATH}"

    @property
    def request_count(self):
        """Number of metadata fetches; asset downloads are counted separately."""
        return self.requests.count(METADATA_PATH)

    def serve(self, payload):
        """Serve `payload` (a Python object) as a 200 JSON response."""
        self.status = 200
        self.body = json.dumps(payload)

    def serve_raw(self, text, status=200, content_type="application/json"):
        """Serve arbitrary text, for malformed-body and error-status cases."""
        self.status = status
        self.body = text
        self.content_type = content_type

    def serve_media(self, entry_id, body=b"media-bytes", content_type="video/mp4", suffix=""):
        """Register the media asset for `entry_id`, optionally under `<id>.<fmt>`."""
        self.assets[f"{METADATA_PATH}/media/{entry_id}{suffix}"] = (body, content_type)

    def serve_preview(self, entry_id, body=b"preview-bytes", content_type="image/png"):
        self.assets[f"{METADATA_PATH}/preview/{entry_id}"] = (body, content_type)

    def serve_assets(self, *entry_ids, **kwargs):
        """Register both the media and the preview asset for each id."""
        for entry_id in entry_ids:
            self.serve_media(entry_id, **kwargs)
            self.serve_preview(entry_id)

    def fail_next(self, path_suffix, statuses):
        """Answer the next requests for `<metadata>/<path_suffix>` with `statuses`."""
        self.pending_failures[f"{METADATA_PATH}/{path_suffix}"] = list(statuses)

    def hits(self, path_suffix):
        """How many times `<metadata>/<path_suffix>` has been requested."""
        return self.requests.count(f"{METADATA_PATH}/{path_suffix}")

    def asset_requests(self):
        """Every asset path requested, in request order."""
        return [path for path in self.requests if path != METADATA_PATH]

    def shutdown(self):
        self._server.shutdown()
        self._server.server_close()

    def _respond(self, handler, status, payload, content_type):
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    def _handler_class(server_self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                server_self.requests.append(self.path)
                server_self.methods.append(self.command)
                if self.path == METADATA_PATH:
                    server_self._respond(
                        self,
                        server_self.status,
                        server_self.body.encode(),
                        server_self.content_type,
                    )
                    return

                scripted = server_self.pending_failures.get(self.path)
                if scripted:
                    server_self._respond(self, scripted.pop(0), b"nope", "text/plain")
                    return

                if self.path in server_self.assets:
                    body, content_type = server_self.assets[self.path]
                    server_self._respond(self, 200, body, content_type)
                    return

                server_self._respond(self, 404, b"missing", "text/plain")

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


def media_names(vault_dir):
    """Sorted filenames stored in the vault's media directory."""
    directory = vault_dir / "media"
    return sorted(path.name for path in directory.iterdir()) if directory.is_dir() else []


def preview_names(vault_dir):
    """Sorted filenames stored in the vault's previews directory."""
    directory = vault_dir / "previews"
    return sorted(path.name for path in directory.iterdir()) if directory.is_dir() else []


def media_stems(vault_dir):
    """Sorted stems of the media files, i.e. the entry ids already downloaded."""
    return sorted(Path(name).stem for name in media_names(vault_dir))


#: Derivation of a full source URL from a version 1 `source_id`.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{}"

#: UNIX-epoch history key used by the v1 fixtures, and its UTC ISO 8601 form.
V1_EPOCH = "1718444400"
V1_EPOCH_ISO = "2024-06-15T09:40:00"

#: ISO 8601 history key used by the v2 fixtures.
V2_STAMP = "2024-06-15T09:40:00"

#: A later ISO 8601 key, for fixtures that need a second observation.
V2_LATER = "2024-06-16T09:40:00"


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


def v3_entry(entry_id, stamp=V2_STAMP, **overrides):
    """A complete version 3 entry: static fields, six histories, annotations."""
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
        "removed": {stamp: False},
        "annotations": [],
    }
    entry.update(overrides)
    return entry


def v3_catalog(episodes=(), streams=(), clips=(), source="http://example.invalid/source.json"):
    """A version 3 catalog holding hand-built entries."""
    return {
        "version": 3,
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


# --- Viewer ---------------------------------------------------------------
#
# The viewer tests drive the real `serve` command as a subprocess and talk to it
# over HTTP, the way a browser would.

#: Shell command `serve` is pointed at as the browser, recording each URL opened.
BROWSER_RECORDER = '#!/bin/sh\nprintf "%s\\n" "$1" >> "$BROWSER_LOG"\n'

#: Bind address `serve` uses when neither --host nor --port is given.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

READY_TIMEOUT = 15


def free_port():
    """A port that was free a moment ago: bound, read back and released."""
    with socket.socket() as probe:
        probe.bind((DEFAULT_HOST, 0))
        return probe.getsockname()[1]


class Viewer:
    """A running `mvault.py serve` process, with an HTTP client for it."""

    def __init__(self, process, host, port, browser_log, server_log):
        self.process = process
        self.base = f"http://{host}:{port}"
        self.browser_log = browser_log
        self.server_log = server_log
        self.session = requests.Session()

    def get(self, path, follow=False):
        return self.session.get(self.base + path, allow_redirects=follow, timeout=10)

    def post(self, data, follow=False):
        return self.session.post(self.base + "/", data=data, allow_redirects=follow, timeout=10)

    def send(self, method, path, body=None, follow=False):
        """Send `method` to `path`; `body` is JSON-encoded unless it is raw text."""
        carrier = {"data": body} if isinstance(body, str) else {"json": body}
        return self.session.request(
            method, self.base + path, allow_redirects=follow, timeout=10, **carrier
        )

    @property
    def cookies(self):
        """What this browser has stored, as a plain name/value mapping."""
        return dict(self.session.cookies)

    def reopen(self, cookies=None):
        """Begin a new browser session, restoring the cookies it kept."""
        self.session = requests.Session()
        for name, value in (cookies or {}).items():
            self.session.cookies.set(name, value)

    @property
    def opened_urls(self):
        """URLs the server asked the browser to open, in order."""
        return self.browser_log.read_text().split() if self.browser_log.is_file() else []

    def output(self):
        return self.server_log.read_text() if self.server_log.is_file() else ""

    def wait_ready(self):
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(f"serve exited early:\n{self.output()}")
            try:
                self.get("/")
                return self
            except requests.RequestException:
                time.sleep(0.05)
        raise AssertionError(f"serve never became ready:\n{self.output()}")

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)


@pytest.fixture
def serve(tmp_path):
    """Start `mvault.py serve` in a directory and return a client for it."""
    running = []
    browser = tmp_path / "browser.sh"
    browser.write_text(BROWSER_RECORDER)
    browser.chmod(0o755)

    def _serve(*args, cwd=None, host=DEFAULT_HOST, port=None, flags=True):
        """Run `serve <args...>`; with no explicit port, take a free one.

        `flags=False` leaves --host and --port off the command line, so the
        server has to fall back to its own default bind address.
        """
        port = free_port() if port is None else port
        browser_log = tmp_path / f"opened-{port}.txt"
        server_log = tmp_path / f"serve-{port}.log"
        options = [f"--host={host}", f"--port={port}"] if flags else []
        with server_log.open("wb") as stream:
            process = subprocess.Popen(
                [sys.executable, str(MVAULT), "serve", *args, *options],
                cwd=str(cwd or tmp_path),
                stdout=stream,
                stderr=subprocess.STDOUT,
                env={**os.environ, "BROWSER": str(browser), "BROWSER_LOG": str(browser_log)},
            )
        viewer = Viewer(process, host, port, browser_log, server_log)
        running.append(viewer)
        return viewer.wait_ready()

    yield _serve
    for viewer in running:
        viewer.stop()


def add_media(vault_dir, *filenames):
    """Put media files into the vault, as a finished download would."""
    media = vault_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        (media / filename).write_bytes(b"media-bytes")


def add_previews(vault_dir, *filenames):
    """Put preview images into the vault, as a finished download would."""
    previews = vault_dir / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        (previews / filename).write_bytes(b"preview-bytes")


def chart_data(html):
    """The machine-readable chart payload a detail page embeds."""
    blocks = re.findall(
        r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    assert len(blocks) == 1, f"expected one embedded payload, got {len(blocks)}"
    return json.loads(blocks[0])


def chart_points(html, field):
    """One charted field's `(timestamp, value)` pairs, in payload order."""
    return [(point["timestamp"], point["value"]) for point in chart_data(html)[field]]


def charted_fields(html):
    """The fields the page actually draws a chart for."""
    return re.findall(r'data-chart="([^"]+)"', html)


def entry_rows(html):
    """The listing's entry rows, one string each."""
    return re.findall(r'<li class="entry[^"]*"[^>]*>.*?</li>', html, re.DOTALL)


def row_for(html, entry_id):
    """The single listing row linking to `entry_id`."""
    matches = [row for row in entry_rows(html) if f"/{entry_id}\"" in row]
    assert len(matches) == 1, f"expected one row for {entry_id}, got {len(matches)}"
    return matches[0]


#: Wording every error response is checked against for leaked internals.
LEAKS = ("Traceback", 'File "', "Exception")


def assert_clean(response):
    """A well-formed HTTP response with no raw exception text in it."""
    assert response.status_code != 500
    assert "Content-Type" in response.headers
    for leak in LEAKS:
        assert leak not in response.text


def is_redirect(response, location):
    """A 302/303 redirect to `location`, ignoring any query the server adds."""
    return response.status_code in (302, 303) and response.headers.get(
        "Location", ""
    ).split("?")[0] == location


# --- Annotations ----------------------------------------------------------

def entry_route(name, category, entry_id):
    """The detail route of one entry, which is also its annotation route."""
    return f"/catalog/{name}/{category}/{entry_id}"


def stored_annotations(vault_dir, category, entry_id):
    """The annotation list stored for one entry, in catalog order."""
    return find_entry(read_catalog(vault_dir), category, entry_id)["annotations"]


def annotation_titles(vault_dir, category, entry_id):
    """Stored annotation titles, in catalog order."""
    return [item["title"] for item in stored_annotations(vault_dir, category, entry_id)]


def annotation_ids(vault_dir, category, entry_id):
    """Stored annotation ids, in catalog order."""
    return [item["id"] for item in stored_annotations(vault_dir, category, entry_id)]


def create(viewer, route, **fields):
    """POST one annotation and assert the request was accepted."""
    response = viewer.send("POST", route, fields)
    assert response.status_code in (302, 303), (response.status_code, response.text[:400])
    return response


def location(response):
    """The `Location` of a redirect, as a path and a query mapping."""
    path, _, query = response.headers.get("Location", "").partition("?")
    return path, parse_qs(query)


def rendered_annotations(html):
    """Ids of the annotations a detail page renders, in page order."""
    return re.findall(r'data-annotation="([^"]+)"', html)
