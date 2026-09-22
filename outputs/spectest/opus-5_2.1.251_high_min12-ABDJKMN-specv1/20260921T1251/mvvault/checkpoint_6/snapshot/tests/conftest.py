"""Shared fixtures for the mvault spec tests.

Every test drives the real CLI surface required by the spec:

    | Console command | `python mvault.py <subcommand> [args...]` | Full CLI behavior |

so the helpers here run `mvault.py` as a subprocess and serve the vault
`source` URL from a real local HTTP server (the spec requires the fetch be an
HTTP `GET` made with `urllib.request`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MVAULT = REPO_ROOT / "mvault.py"

# | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

TRACKED_FIELDS = ("title", "description", "views", "likes", "preview", "removed")
STATIC_FIELDS = ("id", "published", "width", "height")
CATEGORIES = ("episodes", "streams", "clips")

# | Media | `<source>/media/<entry_id>` | ... | Preview | `<source>/preview/<entry_id>` |
SOURCE_DOC_PATH = "/source.json"


def media_path(entry_id, fmt=None):
    """Request path the download phase must use for an entry's media."""
    suffix = f".{fmt}" if fmt else ""
    return f"{SOURCE_DOC_PATH}/media/{entry_id}{suffix}"


def preview_path(entry_id):
    """Request path the download phase must use for an entry's preview."""
    return f"{SOURCE_DOC_PATH}/preview/{entry_id}"


def media_dir(vault):
    return Path(vault) / "media"


def preview_dir(vault):
    return Path(vault) / "previews"


def listing(directory):
    """Sorted file names in a directory (empty when the directory is absent)."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(item.name for item in directory.iterdir() if item.is_file())


def make_source_entry(entry_id: str, **overrides):
    """A source entry carrying all nine required fields with valid types."""
    entry = {
        "id": entry_id,
        "published": "2024-05-01T08:30:00",
        "width": 1920,
        "height": 1080,
        "title": f"Title {entry_id}",
        "description": f"Description {entry_id}",
        "views": 100,
        "likes": 10,
        "preview": f"hash-{entry_id}",
    }
    entry.update(overrides)
    return entry


def make_payload(episodes=None, streams=None, clips=None):
    """A source response: JSON object with `episodes`, `streams`, `clips`."""
    return {
        "episodes": list(episodes or []),
        "streams": list(streams or []),
        "clips": list(clips or []),
    }


class SourceServer:
    """Serves the vault source payload over real HTTP."""

    def __init__(self):
        self.payload = make_payload()
        self.raw_body = None  # when set, served verbatim instead of `payload`
        self.status = 200
        self.requests = []  # (method, path) of every received request
        # Download assets: request path -> (status, body bytes, Content-Type).
        self.assets = {}
        # Request path -> number of remaining transient (5xx) responses to
        # serve before the registered asset is returned.
        self.transient = {}
        self.transient_status = 503
        self.missing_status = 404  # served for unregistered asset paths
        self._lock = threading.Lock()

        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                with server._lock:
                    server.requests.append(("GET", self.path))
                    if self.path == SOURCE_DOC_PATH:
                        asset = None
                        status = server.status
                        if server.raw_body is not None:
                            body = server.raw_body
                            if isinstance(body, str):
                                body = body.encode("utf-8")
                        else:
                            body = json.dumps(server.payload).encode("utf-8")
                        ctype = "application/json"
                    else:
                        asset = server._resolve_asset(self.path)
                        status, body, ctype = asset

                self.send_response(status)
                if ctype is not None:
                    self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802 - http.server API
                with server._lock:
                    server.requests.append(("POST", self.path))
                self.send_response(405)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):  # keep test output clean
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/source.json"

    def _resolve_asset(self, path):
        """Return `(status, body, content_type)` for a download request path.

        Called with `_lock` held. Unregistered paths are "permanently
        unavailable"; registered paths may be preceded by a configurable number
        of transient failures.
        """
        remaining = self.transient.get(path, 0)
        if remaining > 0:
            self.transient[path] = remaining - 1
            return (self.transient_status, b"transient failure", "text/plain")
        asset = self.assets.get(path)
        if asset is None:
            return (self.missing_status, b"not found", "text/plain")
        return asset

    def set_asset(self, path, body=b"payload-bytes", content_type="video/mp4",
                  status=200):
        """Register downloadable content at a request path."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        with self._lock:
            self.assets[path] = (status, body, content_type)

    def set_media(self, entry_id, fmt=None, **kwargs):
        self.set_asset(media_path(entry_id, fmt), **kwargs)

    def set_preview(self, entry_id, **kwargs):
        kwargs.setdefault("content_type", "image/jpeg")
        kwargs.setdefault("body", b"preview-bytes")
        self.set_asset(preview_path(entry_id), **kwargs)

    def serve_entry(self, entry_id, fmt=None, **kwargs):
        """Register both the media and the preview asset for an entry."""
        self.set_media(entry_id, fmt=fmt, **kwargs)
        self.set_preview(entry_id)

    def fail_transiently(self, path, times, status=503):
        """Serve `times` transient failures at `path` before succeeding."""
        with self._lock:
            self.transient[path] = times
            self.transient_status = status

    def hits(self, path):
        """Number of GET requests received for `path`."""
        with self._lock:
            return sum(1 for method, seen in self.requests
                       if method == "GET" and seen == path)

    def paths(self):
        with self._lock:
            return [seen for _method, seen in self.requests]

    def set(self, payload):
        with self._lock:
            self.payload = payload
            self.raw_body = None

    def set_raw(self, body, status=200):
        with self._lock:
            self.raw_body = body
            self.status = status

    def shutdown(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def source():
    server = SourceServer()
    try:
        yield server
    finally:
        server.shutdown()


@pytest.fixture
def run_cli(tmp_path):
    """Run `python mvault.py ...` in an isolated working directory."""

    def _run(*args, cwd=None):
        return subprocess.run(
            [sys.executable, str(MVAULT), *[str(a) for a in args]],
            cwd=str(cwd or tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )

    return _run


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


def read_catalog(workdir, name="vault"):
    return json.loads((Path(workdir) / name / "catalog.json").read_text(encoding="utf-8"))


def find_entry(catalog, entry_id, category=None):
    for cat in ((category,) if category else CATEGORIES):
        for entry in catalog[cat]:
            if entry["id"] == entry_id:
                return entry
    return None


def latest_key(history):
    """Current value key = latest datetime key, in chronological order."""
    return sorted(history)[-1]


def current(history):
    return history[latest_key(history)]


def keys_sorted(history):
    return sorted(history)


@pytest.fixture
def vault(run_cli, workdir, source):
    """An initialized vault named `vault` pointed at the local source server."""
    result = run_cli("init", "vault", source.url)
    assert result.returncode == 0, result.stderr
    return Path(workdir) / "vault"


@pytest.fixture
def helpers():
    class _H:
        make_source_entry = staticmethod(make_source_entry)
        make_payload = staticmethod(make_payload)
        read_catalog = staticmethod(read_catalog)
        find_entry = staticmethod(find_entry)
        latest_key = staticmethod(latest_key)
        current = staticmethod(current)
        keys_sorted = staticmethod(keys_sorted)
        media_path = staticmethod(media_path)
        preview_path = staticmethod(preview_path)
        media_dir = staticmethod(media_dir)
        preview_dir = staticmethod(preview_dir)
        listing = staticmethod(listing)
        make_v1_entry = staticmethod(make_v1_entry)
        make_v2_entry = staticmethod(make_v2_entry)

    return _H


def copy_tree_snapshot(path):
    """Byte-level snapshot of a directory, for `leave the vault unchanged`."""
    snap = {}
    for item in sorted(Path(path).rglob("*")):
        if item.is_file():
            snap[str(item.relative_to(path))] = item.read_bytes()
    return snap


@pytest.fixture
def snapshot():
    return copy_tree_snapshot


@pytest.fixture
def restore():
    def _restore(src, dst):
        shutil.rmtree(dst)
        shutil.copytree(src, dst)

    return _restore


# --------------------------------------------------------------------------
# legacy (version 1 / version 2) catalog helpers
#
# | `1` | Supported | Flat `entries` list; `source_id`; UNIX-epoch history
#   keys; no `removed`; no `annotations` |
# | `2` | Supported | Category arrays; full `source`; ISO 8601 history keys;
#   no `removed`; no `annotations` |
# --------------------------------------------------------------------------

V1_EPOCH = "1718444400"           # UNIX epoch seconds, as a string key
V1_EPOCH_ISO = "2024-06-15T09:40:00"  # the same instant, ISO 8601 in UTC
V1_EPOCH_LATER = "1718448000"
V1_EPOCH_LATER_ISO = "2024-06-15T10:40:00"

V2_STAMP = "2024-06-15T09:40:00"

V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{source_id}"


def make_v1_entry(entry_id, epoch=V1_EPOCH, **overrides):
    """A version 1 entry: UNIX-epoch string history keys, no removed/annotations."""
    entry = {
        "id": entry_id,
        "published": "2024-05-01T08:30:00",
        "width": 1920,
        "height": 1080,
        "title": {epoch: f"Title {entry_id}"},
        "description": {epoch: f"Description {entry_id}"},
        "views": {epoch: 100},
        "likes": {epoch: 10},
        "preview": {epoch: f"hash-{entry_id}"},
    }
    entry.update(overrides)
    return entry


def make_v1_catalog(entries=None, source_id="chan-1", **overrides):
    """| `version` | integer | `1` | + | `source_id` | + flat | `entries` |"""
    catalog = {
        "version": 1,
        "source_id": source_id,
        "entries": list(entries or []),
    }
    catalog.update(overrides)
    return catalog


def make_v2_entry(entry_id, stamp=V2_STAMP, **overrides):
    """A version 2 entry: ISO 8601 history keys, no removed/annotations."""
    entry = {
        "id": entry_id,
        "published": "2024-05-01T08:30:00",
        "width": 1920,
        "height": 1080,
        "title": {stamp: f"Title {entry_id}"},
        "description": {stamp: f"Description {entry_id}"},
        "views": {stamp: 100},
        "likes": {stamp: 10},
        "preview": {stamp: f"hash-{entry_id}"},
    }
    entry.update(overrides)
    return entry


def make_v2_catalog(source, episodes=None, streams=None, clips=None, **overrides):
    """| `version` | `2` | + full `source` + `episodes`/`streams`/`clips` arrays."""
    catalog = {
        "version": 2,
        "source": source,
        "episodes": list(episodes or []),
        "streams": list(streams or []),
        "clips": list(clips or []),
    }
    catalog.update(overrides)
    return catalog


def write_vault(workdir, catalog, name="vault", raw=None):
    """Create `<workdir>/<name>/catalog.json` holding `catalog` (or `raw` text)."""
    vault_dir = Path(workdir) / name
    vault_dir.mkdir(parents=True, exist_ok=True)
    text = raw if raw is not None else json.dumps(catalog, indent=2) + "\n"
    (vault_dir / "catalog.json").write_text(text, encoding="utf-8")
    return vault_dir


@pytest.fixture
def make_vault(workdir):
    """Materialize a vault directory from a catalog object (any version)."""

    def _make(catalog=None, name="vault", raw=None):
        return write_vault(workdir, catalog, name=name, raw=raw)

    return _make


@pytest.fixture
def legacy(source):
    """Builders for legacy catalogs, with `source` bound to the test server."""

    class _L:
        V1_EPOCH = V1_EPOCH
        V1_EPOCH_ISO = V1_EPOCH_ISO
        V1_EPOCH_LATER = V1_EPOCH_LATER
        V1_EPOCH_LATER_ISO = V1_EPOCH_LATER_ISO
        V2_STAMP = V2_STAMP
        V1_SOURCE_TEMPLATE = V1_SOURCE_TEMPLATE
        v1_entry = staticmethod(make_v1_entry)
        v1_catalog = staticmethod(make_v1_catalog)
        v2_entry = staticmethod(make_v2_entry)

        @staticmethod
        def v2_catalog(episodes=None, streams=None, clips=None, **overrides):
            return make_v2_catalog(source.url, episodes, streams, clips, **overrides)

        @staticmethod
        def v1_source(source_id):
            return V1_SOURCE_TEMPLATE.format(source_id=source_id)

    return _L


# --------------------------------------------------------------------------
# version 3 catalog helpers, for hand-built `digest` fixtures
#
# | v3 | `Episodes`, `Streams`, `Clips` | Full removal detection | ISO 8601
#   string keys |
# --------------------------------------------------------------------------

V3_STAMP_1 = "2024-06-15T09:40:00"
V3_STAMP_2 = "2024-06-16T09:40:00"
V3_STAMP_3 = "2024-06-17T09:40:00"


def make_v3_entry(entry_id, stamp=V3_STAMP_1, **overrides):
    """A version 3 entry: ISO 8601 history keys plus `removed`/`annotations`."""
    entry = make_v2_entry(entry_id, stamp=stamp)
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    entry.update(overrides)
    return entry


def make_v3_catalog(source, episodes=None, streams=None, clips=None, **overrides):
    catalog = {
        "version": 3,
        "source": source,
        "episodes": list(episodes or []),
        "streams": list(streams or []),
        "clips": list(clips or []),
    }
    catalog.update(overrides)
    return catalog


@pytest.fixture
def catalogs(source):
    """Builders for hand-written v3 catalogs bound to the test source server."""

    class _C:
        STAMP_1 = V3_STAMP_1
        STAMP_2 = V3_STAMP_2
        STAMP_3 = V3_STAMP_3
        entry = staticmethod(make_v3_entry)

        @staticmethod
        def catalog(episodes=None, streams=None, clips=None, **overrides):
            return make_v3_catalog(source.url, episodes, streams, clips, **overrides)

    return _C


def digest_lines(stdout):
    """Digest body lines (everything but the trailing metadata line)."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    return lines[:-1]


def trailing_line(stdout):
    """| Trailing line | Metadata about the digest run |"""
    lines = [line for line in stdout.splitlines() if line.strip()]
    return lines[-1]


def section(stdout, header):
    """Raw lines nested under a `header` line, up to the next same-indent line.

    Accepts either the full digest stdout or an already-extracted section, so
    a category section can be searched for its change-type groups.
    """
    lines = digest_lines(stdout) if isinstance(stdout, str) else list(stdout)
    collected = []
    depth = None
    for line in lines:
        indent = len(line) - len(line.lstrip())
        if depth is None:
            if line.strip().rstrip(":").lower() == header.rstrip(":").lower():
                depth = indent
            continue
        if indent <= depth:
            break
        collected.append(line)
    return collected


def group(stdout, category, name):
    """Entry lines of one change-type group inside one category."""
    return [line.strip() for line in section(section(stdout, category), name)]


def headers(stdout):
    """Every header line (a line ending in `:`), in order, stripped."""
    return [line.strip().rstrip(":") for line in digest_lines(stdout)
            if line.strip().endswith(":")]


@pytest.fixture
def digest():
    class _D:
        lines = staticmethod(digest_lines)
        trailing = staticmethod(trailing_line)
        section = staticmethod(section)
        group = staticmethod(group)
        headers = staticmethod(headers)

    return _D


# --------------------------------------------------------------------------
# viewer (`serve`) helpers
#
# | Syntax | `python mvault.py serve [<name>] [--host=<host>] [--port=<port>]` |
# | Default bind address | `127.0.0.1:8840` |
#
# The viewer is driven exactly like a browser would drive it: a real child
# process running `python mvault.py serve`, spoken to over real HTTP with
# `http.client` so redirects, status codes and cookies stay visible.
# --------------------------------------------------------------------------

import http.client
import time
import urllib.parse
from collections import namedtuple
from html import unescape as html_unescape

VIEWER_DEFAULT_HOST = "127.0.0.1"
VIEWER_DEFAULT_PORT = 8840

# Line the server prints once it is bound, e.g. `... on 127.0.0.1:41234`.
LISTEN_RE = re.compile(r"(?:listening|serving)[^\n]*?([0-9A-Za-z_.:\[\]-]+):(\d+)",
                       re.IGNORECASE)
# Any absolute http URL printed by `serve` (the browser target).
URL_RE = re.compile(r"http://[^\s\"'<>]+")

_UNSET = object()

Response = namedtuple("Response", "status headers body location path")


def _connect_host(host):
    """A host string that a test client can actually connect to."""
    if host in ("0.0.0.0", "::", "[::]", ""):
        return "127.0.0.1"
    return host


class ViewerClient:
    """One browser: a cookie jar plus an HTTP connection factory."""

    def __init__(self, host, port, cookies=None):
        self.host = _connect_host(host)
        self.port = int(port)
        self.cookies = dict(cookies or {})

    def _headers(self):
        headers = {"Accept": "text/html"}
        if self.cookies:
            headers["Cookie"] = "; ".join(
                f"{key}={value}" for key, value in self.cookies.items())
        return headers

    def _store_cookies(self, response):
        for key, value in response.getheaders():
            if key.lower() != "set-cookie":
                continue
            pair = value.split(";", 1)[0].strip()
            if "=" in pair:
                name, _, raw = pair.partition("=")
                self.cookies[name.strip()] = raw.strip()

    def _once(self, method, path, body=None, content_type=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=15)
        try:
            headers = self._headers()
            payload = None
            if body is not None:
                payload = body if isinstance(body, bytes) else body.encode("utf-8")
                headers["Content-Type"] = (content_type
                                           or "application/x-www-form-urlencoded")
                headers["Content-Length"] = str(len(payload))
            conn.request(method, path, body=payload, headers=headers)
            raw = conn.getresponse()
            text = raw.read().decode("utf-8", "replace")
            self._store_cookies(raw)
            return Response(raw.status, dict(raw.getheaders()), text,
                            raw.getheader("Location"), path)
        finally:
            conn.close()

    def request(self, method, path, body=None, follow=False, limit=6,
                content_type=None):
        response = self._once(method, path, body, content_type)
        while follow and response.status in (301, 302, 303, 307, 308) and limit > 0:
            target = urllib.parse.urlsplit(
                urllib.parse.urljoin(f"http://{self.host}:{self.port}{response.path}",
                                     response.location or "/"))
            path = target.path or "/"
            if target.query:
                path = f"{path}?{target.query}"
            response = self._once("GET", path)
            limit -= 1
        return response

    def get(self, path, follow=False, **kwargs):
        return self.request("GET", path, follow=follow, **kwargs)

    def post(self, path, fields=None, body=None, follow=False):
        if body is None:
            body = urllib.parse.urlencode(fields or {})
        return self.request("POST", path, body=body, follow=follow)

    def send_json(self, method, path, payload=_UNSET, raw=_UNSET, follow=False,
                  content_type="application/json"):
        """One annotation request: a JSON body under an arbitrary method.

        | `POST` | Create annotation | JSON with `title`, `timecode`, optional
          `body` | ... |

        ``raw`` sends body bytes verbatim (for the malformed-JSON cases);
        ``payload`` is serialized with `json.dumps`. Passing neither sends no
        body at all.
        """
        if raw is not _UNSET:
            body = raw
        elif payload is not _UNSET:
            body = json.dumps(payload)
        else:
            body = None
        return self.request(method, path, body=body, follow=follow,
                            content_type=content_type if body is not None else None)

    def fresh(self):
        """A different browser: same server, no cookies."""
        return ViewerClient(self.host, self.port)

    def later_session(self):
        """The same browser, later: cookies survive, connection does not."""
        return ViewerClient(self.host, self.port, cookies=self.cookies)


class ViewerProcess:
    """A running `python mvault.py serve` child process."""

    def __init__(self, workdir, args, env=None):
        self.workdir = Path(workdir)
        self.log_path = self.workdir / f"viewer-{os.getpid()}-{time.time_ns()}.log"
        self._log = self.log_path.open("w", encoding="utf-8")
        run_env = dict(os.environ)
        # Never let a real browser launch during the test run.
        run_env["BROWSER"] = "/bin/true"
        run_env.update(env or {})
        self.proc = subprocess.Popen(
            [sys.executable, str(MVAULT), "serve", *[str(a) for a in args]],
            cwd=str(self.workdir),
            stdout=self._log,          # log to a file, never an undrained pipe
            stderr=subprocess.STDOUT,
            env=run_env,
        )
        self.host, self.port = self._wait_until_listening()
        self.client = ViewerClient(self.host, self.port)

    def output(self):
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _wait_until_listening(self, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(
                    f"serve exited with {self.proc.returncode}:\n{self.output()}")
            match = LISTEN_RE.search(self.output())
            if match:
                host, port = match.group(1), int(match.group(2))
                if self._port_answers(_connect_host(host), port):
                    return host, port
            time.sleep(0.05)
        raise AssertionError(f"serve never reported a listening address:\n"
                             f"{self.output()}")

    @staticmethod
    def _port_answers(host, port):
        try:
            conn = http.client.HTTPConnection(host, port, timeout=2)
            conn.request("GET", "/")
            conn.getresponse().read()
            conn.close()
            return True
        except OSError:
            return False

    def urls(self):
        """Every absolute http URL the process printed."""
        return URL_RE.findall(self.output())

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()          # by PID, via the Popen handle
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._log.close()


@pytest.fixture
def serve(workdir):
    """Start `mvault.py serve` in the test working directory."""
    started = []

    def _serve(*args, cwd=None, port=0, env=None):
        argv = list(args)
        if port is not None and not any(str(a).startswith("--port") for a in argv):
            argv.append(f"--port={port}")
        process = ViewerProcess(cwd or workdir, argv, env=env)
        started.append(process)
        return process

    try:
        yield _serve
    finally:
        for process in started:
            process.stop()


def free_port():
    """A port number that was free a moment ago."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def viewer_helpers():
    class _V:
        DEFAULT_HOST = VIEWER_DEFAULT_HOST
        DEFAULT_PORT = VIEWER_DEFAULT_PORT
        free_port = staticmethod(free_port)
        client = ViewerClient
        entry_blocks = staticmethod(entry_blocks)
        entry_block = staticmethod(entry_block)
        link = staticmethod(viewer_link)
        order_of = staticmethod(order_of)

    return _V


def viewer_link(name, category, entry_id, host=VIEWER_DEFAULT_HOST,
                port=VIEWER_DEFAULT_PORT):
    """| Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |"""
    return f"http://{host}:{port}/catalog/{name}/{category}/{entry_id}"


ENTRY_HREF_RE = re.compile(r"/catalog/[^/\s\"']+/[^/\s\"']+/([^\s\"'<>]+)")


def entry_blocks(html):
    """Map entry id -> the HTML chunk that surrounds its entry link.

    The chunk runs from the end of the previous entry link to the end of the
    element holding this one, which is enough to compare how two entries are
    rendered without assuming any particular markup.
    """
    blocks = {}
    matches = list(re.finditer(r"<(li|tr|div|p|article|section)\b[^>]*>", html,
                               re.IGNORECASE))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        chunk = html[match.start():end]
        closing = re.search(rf"</{match.group(1)}\s*>", chunk, re.IGNORECASE)
        if closing:
            chunk = chunk[:closing.end()]
        href = ENTRY_HREF_RE.search(chunk)
        if href:
            blocks.setdefault(href.group(1), chunk)
    return blocks


def entry_block(html, entry_id):
    return entry_blocks(html).get(entry_id, "")


def order_of(html, ids):
    """The ids, ordered by where their entry link first appears in the page."""
    positions = {}
    for entry_id in ids:
        index = html.find(f"/{entry_id}\"")
        if index < 0:
            index = html.find(entry_id)
        positions[entry_id] = index
    return [entry_id for entry_id in sorted(ids, key=lambda k: positions[k])
            if positions[entry_id] >= 0]


# --------------------------------------------------------------------------
# entry detail pages, chart data and `/vault` static assets
#
# | `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for matching
#   entry |
# | Embedding style | Machine-readable structured data embedded in HTML |
# | Payload container and key names | Unspecified as long as the payload
#   remains machine-readable |
#
# Because the container and key names are explicitly unspecified, the readers
# below never assume them: they parse every machine-readable block on the page
# and search the resulting structure for point sequences.
# --------------------------------------------------------------------------

CHART_FIELDS = ("views", "likes")

JSON_SCRIPT_RE = re.compile(
    r"<script\b[^>]*\btype\s*=\s*[\"']application/(?:ld\+)?json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL)

VAULT_URL_RE = re.compile(r"/vault/[^\s\"'<>\\]+")


def detail_path(name, category, entry_id):
    """| `GET` | `/catalog/<name>/<category>/<id>` |"""
    return f"/catalog/{name}/{category}/{entry_id}"


def listing_path(name, category):
    return f"/catalog/{name}/{category}"


def media_url(name, filename):
    """| `GET` | `/vault/<name>/media/<file>` |"""
    return f"/vault/{name}/media/{filename}"


def preview_url(name, entry_id):
    """| `GET` | `/vault/<name>/preview/<id>` |"""
    return f"/vault/{name}/preview/{entry_id}"


def write_media(vault, filename, body=b"media-bytes"):
    """Put a downloaded media file into `<vault>/media/`."""
    directory = Path(vault) / "media"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(body)
    return path


def write_preview(vault, filename, body=b"preview-bytes"):
    """Put a downloaded preview asset into `<vault>/previews/`."""
    directory = Path(vault) / "previews"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(body)
    return path


def vault_urls(html):
    """Every `/vault/...` reference the page carries, in document order."""
    return [url.replace("&amp;", "&") for url in VAULT_URL_RE.findall(html)]


def json_blocks(html):
    """Every machine-readable JSON payload embedded in the page."""
    payloads = []
    for raw in JSON_SCRIPT_RE.findall(html):
        text = raw.strip()
        if not text:
            continue
        try:
            payloads.append(json.loads(text))
        except ValueError:
            continue
    return payloads


def _as_point(item):
    """One `(timestamp, value)` pair, whatever shape the payload wrapped it in."""
    if isinstance(item, (list, tuple)):
        if len(item) != 2:
            return None
        stamp, value = item
        if isinstance(stamp, str) and (value is None or _is_number(value)):
            return (stamp, value)
        return None
    if isinstance(item, dict):
        if len(item) == 1:
            (key, value), = item.items()
            if isinstance(key, str) and (value is None or _is_number(value)):
                return (key, value)
        stamps = [v for v in item.values() if isinstance(v, str)]
        values = [v for v in item.values() if v is None or _is_number(v)]
        if len(stamps) == 1 and len(values) == 1 and len(item) == 2:
            return (stamps[0], values[0])
    return None


def _is_number(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _points_of(node):
    """`node` read as a sequence of points, or `None` if it is not one."""
    if isinstance(node, list):
        points = [_as_point(item) for item in node]
        if all(point is not None for point in points):
            return points
        return None
    if isinstance(node, dict):
        # A history-shaped payload: {"<timestamp>": <value>, ...}
        if all(isinstance(key, str) for key in node) and \
                all(value is None or _is_number(value) for value in node.values()):
            return list(node.items())
    return None


def _collect_series(node, label, found):
    if isinstance(node, dict):
        # {"field": "views", "points": [...]} and friends.
        named = [value for value in node.values()
                 if isinstance(value, str) and value in CHART_FIELDS]
        if len(named) == 1:
            for value in node.values():
                points = _points_of(value) if not isinstance(value, str) else None
                if points is not None:
                    found.setdefault(named[0], points)
        for key, value in node.items():
            if isinstance(key, str) and key in CHART_FIELDS:
                points = _points_of(value)
                if points is not None:
                    found.setdefault(key, points)
            _collect_series(value, key if isinstance(key, str) else label, found)
    elif isinstance(node, list):
        if label in CHART_FIELDS:
            points = _points_of(node)
            if points is not None:
                found.setdefault(label, points)
        for item in node:
            _collect_series(item, label, found)


def chart_series(html):
    """`{field: [(timestamp, value), ...]}` recovered from the page's payloads."""
    found = {}
    for payload in json_blocks(html):
        _collect_series(payload, None, found)
    return found


def chart_points(html, field):
    """The `(timestamp, value)` pairs charted for `field` (empty when absent)."""
    return chart_series(html).get(field, [])


def chart_timestamps(html, field):
    return [stamp for stamp, _ in chart_points(html, field)]


def chart_values(html, field):
    return [value for _, value in chart_points(html, field)]


def history_of(points):
    """A history dict from `(key, value)` pairs, for building fixtures."""
    return {key: value for key, value in points}


@pytest.fixture
def detail():
    """Readers for entry detail pages, chart payloads and `/vault` assets."""

    class _D:
        FIELDS = CHART_FIELDS
        path = staticmethod(detail_path)
        listing = staticmethod(listing_path)
        media_url = staticmethod(media_url)
        preview_url = staticmethod(preview_url)
        write_media = staticmethod(write_media)
        write_preview = staticmethod(write_preview)
        vault_urls = staticmethod(vault_urls)
        json_blocks = staticmethod(json_blocks)
        series = staticmethod(chart_series)
        points = staticmethod(chart_points)
        timestamps = staticmethod(chart_timestamps)
        values = staticmethod(chart_values)
        history = staticmethod(history_of)

    return _D


# --------------------------------------------------------------------------
# annotation helpers
#
# | `POST` | Create annotation | JSON with `title`, `timecode`, optional `body`
#   | Redirect to entry detail page with `?timecode=<seconds>` |
# | `PATCH` | Update annotation | JSON with `id` and at least one of `title` or
#   `body` | Redirect to entry detail page |
# | `DELETE` | Delete annotation | JSON with `id` | Redirect to entry detail
#   page |
# --------------------------------------------------------------------------

REDIRECT_STATUSES = (301, 302, 303, 307, 308)

TAG_RE = re.compile(r"<[^>]*>")
SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_RE = re.compile(r"<style\b.*?</style>", re.IGNORECASE | re.DOTALL)


def visible_text(html):
    """The page text a reader actually sees, with runs of space collapsed.

    Used for "| ... | visibly rendering stored annotations ... |": a rendering
    that only hides the value in an attribute or in the embedded JSON payload
    does not show up here.
    """
    text = SCRIPT_RE.sub(" ", html)
    text = STYLE_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    return " ".join(html_unescape(text).split())


def redirect_location(response):
    """The `Location` of a redirect, as `(path, query-dict)`."""
    assert response.status in REDIRECT_STATUSES, \
        f"expected a redirect, got {response.status}: {response.body[:400]}"
    assert response.location, "redirect carries no Location header"
    split = urllib.parse.urlsplit(response.location)
    return split.path, urllib.parse.parse_qs(split.query)


def redirect_path(response):
    return redirect_location(response)[0]


def redirect_timecode(response):
    """| Create-success redirect value | Integer whole seconds |"""
    values = redirect_location(response)[1].get("timecode", [])
    assert len(values) == 1, f"expected one timecode value, got {values!r}"
    return values[0]


def annotations_of(workdir, name="vault", entry_id=None, category=None):
    """| Catalog location | Entry object key `annotations` |"""
    catalog = read_catalog(workdir, name)
    entry = find_entry(catalog, entry_id, category)
    assert entry is not None, f"no entry {entry_id!r} in {name}"
    return entry.get("annotations")


def annotation_by_id(workdir, name, entry_id, annotation_id, category=None):
    for item in annotations_of(workdir, name, entry_id, category) or []:
        if isinstance(item, dict) and item.get("id") == annotation_id:
            return item
    return None


def only_annotation(workdir, name="vault", entry_id=None, category=None):
    stored = annotations_of(workdir, name, entry_id, category)
    assert isinstance(stored, list) and len(stored) == 1, f"stored: {stored!r}"
    return stored[0]


def backup_catalog(workdir, name="vault"):
    """The `catalog.bak` written before persisting annotation changes."""
    path = Path(workdir) / name / "catalog.bak"
    assert path.is_file(), f"no catalog.bak in vault {name!r}"
    return json.loads(path.read_text(encoding="utf-8"))


def has_backup(workdir, name="vault"):
    return (Path(workdir) / name / "catalog.bak").is_file()


def catalog_text(workdir, name="vault"):
    return (Path(workdir) / name / "catalog.json").read_text(encoding="utf-8")


class _Annotate:
    """Drives the three annotation methods against one entry."""

    REDIRECTS = REDIRECT_STATUSES

    path = staticmethod(detail_path)
    stored = staticmethod(annotations_of)
    by_id = staticmethod(annotation_by_id)
    only = staticmethod(only_annotation)
    backup = staticmethod(backup_catalog)
    has_backup = staticmethod(has_backup)
    catalog_text = staticmethod(catalog_text)
    text = staticmethod(visible_text)
    location = staticmethod(redirect_location)
    target = staticmethod(redirect_path)
    timecode = staticmethod(redirect_timecode)

    @staticmethod
    def send(client, method, name, category, entry_id, payload=_UNSET,
             raw=_UNSET, **kwargs):
        return client.send_json(method, detail_path(name, category, entry_id),
                                payload=payload, raw=raw, **kwargs)

    @staticmethod
    def create(client, name, category, entry_id, payload=_UNSET, **kwargs):
        return _Annotate.send(client, "POST", name, category, entry_id,
                              payload=payload, **kwargs)

    @staticmethod
    def update(client, name, category, entry_id, payload=_UNSET, **kwargs):
        return _Annotate.send(client, "PATCH", name, category, entry_id,
                              payload=payload, **kwargs)

    @staticmethod
    def remove(client, name, category, entry_id, payload=_UNSET, **kwargs):
        return _Annotate.send(client, "DELETE", name, category, entry_id,
                              payload=payload, **kwargs)

    @staticmethod
    def make(client, name, category, entry_id, title="Note", timecode="90",
             **extra):
        """Create one annotation and return its stored id (asserting success)."""
        payload = {"title": title, "timecode": timecode}
        payload.update(extra)
        response = _Annotate.create(client, name, category, entry_id, payload)
        assert response.status in REDIRECT_STATUSES, \
            f"create failed with {response.status}: {response.body[:400]}"
        return response


@pytest.fixture
def annotate():
    """Readers and writers for entry annotations."""
    return _Annotate
