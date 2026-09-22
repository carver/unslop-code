"""Shared fixtures for the mvault spec tests.

Everything is exercised through the CLI surface required by the spec:
    python mvault.py <subcommand> [args...]
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MVAULT = os.path.join(REPO_ROOT, "mvault.py")


class Result:
    def __init__(self, proc):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Result(rc=%r, stdout=%r, stderr=%r)" % (
            self.returncode,
            self.stdout,
            self.stderr,
        )


@pytest.fixture
def run(tmp_path):
    """Invoke `python mvault.py ...` inside an isolated working directory."""

    def _run(*args, cwd=None):
        proc = subprocess.run(
            [sys.executable, MVAULT, *[str(a) for a in args]],
            cwd=str(cwd or tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return Result(proc)

    return _run


class _Asset:
    """One downloadable asset served at a fixed path.

    `fail_times` responses of `fail_status` are served first, which models a
    transient failure that later succeeds.
    """

    def __init__(self, body, content_type, status, fail_times, fail_status):
        self.body = body
        self.content_type = content_type
        self.status = status
        self.fail_times = fail_times
        self.fail_status = fail_status

    def next_response(self):
        if self.fail_times > 0:
            self.fail_times -= 1
            return self.fail_status, "text/plain", b"transient"
        return self.status, self.content_type, self.body


class _Source:
    """A tiny HTTP source whose payload can be swapped between syncs."""

    def __init__(self):
        self.body = b"{}"
        self.status = 200
        self.content_type = "application/json"
        self.requests = []
        self.delay = 0.0
        self.assets = {}

    def set_payload(self, obj):
        self.body = json.dumps(obj).encode("utf-8")

    def set_raw(self, data, status=200, content_type="application/json"):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.body = data
        self.status = status
        self.content_type = content_type

    # -- downloadable assets -------------------------------------------------

    def set_asset(self, path, body=b"binary-data", content_type="video/mp4",
                  status=200, fail_times=0, fail_status=503):
        """Serve `body` at `path` (a URL path such as `/source.json/media/e1`)."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.assets[path] = _Asset(body, content_type, status, fail_times,
                                   fail_status)

    def set_media(self, eid, fmt=None, **kw):
        self.set_asset(media_path(eid, fmt), **kw)

    def set_preview(self, eid, **kw):
        kw.setdefault("content_type", "image/jpeg")
        self.set_asset(preview_path(eid), **kw)

    def set_entry_assets(self, eid, fmt=None, **kw):
        """Serve both the media and the preview asset for one entry."""
        self.set_media(eid, fmt, **kw)
        self.set_preview(eid)

    def hits(self, path):
        return sum(1 for method, seen in self.requests if seen == path)


SOURCE_DOC = "/source.json"


def media_path(eid, fmt=None):
    """URL path of an entry's media asset, per Download Sources and Targets."""
    suffix = ".%s" % fmt if fmt else ""
    return "%s/media/%s%s" % (SOURCE_DOC, eid, suffix)


def preview_path(eid):
    """URL path of an entry's preview asset."""
    return "%s/preview/%s" % (SOURCE_DOC, eid)


@pytest.fixture
def source():
    """Serve mutable JSON over HTTP; `source.url` is the vault source URL."""
    state = _Source()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.requests.append(("GET", self.path))
            asset = state.assets.get(self.path)
            if asset is not None:
                status, content_type, body = asset.next_response()
            elif "/media/" in self.path or "/preview/" in self.path:
                # An asset path nobody configured is permanently unavailable.
                status, content_type, body = 404, "text/plain", b"not found"
            else:
                status, content_type, body = (
                    state.status, state.content_type, state.body
                )
            self.send_response(status)
            if content_type is not None:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # recorded so tests can assert GET was used
            state.requests.append(("POST", self.path))
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):  # silence stderr logging
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = "http://127.0.0.1:%d/source.json" % server.server_address[1]
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def entry(eid, published="2024-01-01T00:00:00", **over):
    """A well-formed source entry with all nine required fields."""
    data = {
        "id": eid,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": "Title %s" % eid,
        "description": "Description %s" % eid,
        "views": 100,
        "likes": 10,
        "preview": "hash-%s" % eid,
    }
    data.update(over)
    return data


def payload(episodes=(), streams=(), clips=()):
    return {
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def read_catalog(tmp_path, name="vault"):
    with open(os.path.join(str(tmp_path), name, "catalog.json")) as fh:
        return json.load(fh)


def find(catalog, eid, category="episodes"):
    for item in catalog[category]:
        if item["id"] == eid:
            return item
    return None


def history_keys(entry_obj, field):
    """History keys in chronological order."""
    return sorted(entry_obj[field].keys())


def current(entry_obj, field):
    """Current value = value at the latest datetime key."""
    hist = entry_obj[field]
    return hist[max(hist.keys(), key=lambda k: k)]


@pytest.fixture
def vault(run, source, tmp_path):
    """An initialized vault named `vault` pointed at the HTTP source."""
    result = run("init", "vault", source.url)
    assert result.returncode == 0, result
    return tmp_path / "vault"


# ---------------------------------------------------------------------------
# legacy-catalog helpers (spec: Supported Versions / Multi-Version Loading)
# ---------------------------------------------------------------------------

LEGACY_SOURCE_PREFIX = "https://media.example.com/channel/"

# Epoch seconds and their UTC `YYYY-MM-DDTHH:MM:SS` renderings.
EPOCH_TO_ISO = {
    "1700000000": "2023-11-14T22:13:20",
    "1718444400": "2024-06-15T09:40:00",
    "1718448000": "2024-06-15T10:40:00",
    "0": "1970-01-01T00:00:00",
}


def v1_entry(eid, published="2024-01-01T00:00:00", stamp="1718444400", **over):
    """A well-formed version 1 entry: UNIX-epoch history keys, no `removed`."""
    data = {
        "id": eid,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": {stamp: "Title %s" % eid},
        "description": {stamp: "Description %s" % eid},
        "views": {stamp: 100},
        "likes": {stamp: 10},
        "preview": {stamp: "hash-%s" % eid},
    }
    data.update(over)
    return data


def v2_entry(eid, published="2024-01-01T00:00:00", stamp="2024-06-15T09:40:00",
             **over):
    """A well-formed version 2 entry: ISO 8601 history keys, no `removed`."""
    data = {
        "id": eid,
        "published": published,
        "width": 1920,
        "height": 1080,
        "title": {stamp: "Title %s" % eid},
        "description": {stamp: "Description %s" % eid},
        "views": {stamp: 100},
        "likes": {stamp: 10},
        "preview": {stamp: "hash-%s" % eid},
    }
    data.update(over)
    return data


def v1_catalog(source_id="chan-1", entries=()):
    return {"version": 1, "source_id": source_id, "entries": list(entries)}


def v2_catalog(source="https://example.test/source.json", episodes=(),
               streams=(), clips=()):
    return {
        "version": 2,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def v3_catalog(source="https://example.test/source.json", episodes=(),
               streams=(), clips=()):
    return {
        "version": 3,
        "source": source,
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }


def write_vault(tmp_path, catalog, name="vault"):
    """Create `<tmp_path>/<name>/catalog.json` holding `catalog` verbatim.

    `catalog` may be a str/bytes to write raw (invalid JSON fixtures).
    """
    vault_dir = os.path.join(str(tmp_path), name)
    os.makedirs(vault_dir, exist_ok=True)
    path = os.path.join(vault_dir, "catalog.json")
    if isinstance(catalog, bytes):
        with open(path, "wb") as fh:
            fh.write(catalog)
    elif isinstance(catalog, str):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(catalog)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(catalog, fh, indent=2)
            fh.write("\n")
    return vault_dir


def catalog_text(tmp_path, name="vault"):
    with open(os.path.join(str(tmp_path), name, "catalog.json")) as fh:
        return fh.read()


def backup_path(tmp_path, name="vault"):
    return os.path.join(str(tmp_path), name, "catalog.bak")


def read_backup(tmp_path, name="vault"):
    with open(backup_path(tmp_path, name)) as fh:
        return json.load(fh)


def all_entries(catalog):
    """Every entry in every category of a v3 catalog."""
    out = []
    for category in ("episodes", "streams", "clips"):
        out.extend(catalog.get(category, []))
    return out


# ---------------------------------------------------------------------------
# download helpers (spec: Download Sources and Targets / Download Rules)
# ---------------------------------------------------------------------------

def media_dir(tmp_path, name="vault"):
    return os.path.join(str(tmp_path), name, "media")


def previews_dir(tmp_path, name="vault"):
    return os.path.join(str(tmp_path), name, "previews")


def listdir(path):
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


def media_files(tmp_path, name="vault"):
    return listdir(media_dir(tmp_path, name))


def preview_files(tmp_path, name="vault"):
    return listdir(previews_dir(tmp_path, name))


def stems(filenames):
    """Filenames reduced to the part before the first dot."""
    return sorted(f.split(".", 1)[0] for f in filenames)


def write_file(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as fh:
        fh.write(data)
    return path


# ---------------------------------------------------------------------------
# digest helpers (spec: `digest` Format-Aware Loading)
# ---------------------------------------------------------------------------

def v3_entry(eid, published="2024-01-01T00:00:00", stamp="2024-06-15T09:40:00",
             **over):
    """A well-formed version 3 entry: ISO 8601 keys plus `removed`."""
    data = v2_entry(eid, published=published, stamp=stamp)
    data["removed"] = {stamp: False}
    data["annotations"] = []
    data.update(over)
    return data


def lines(text):
    return [line for line in text.splitlines() if line.strip()]


def trailing_line(text):
    """The last non-blank line of digest output."""
    body = lines(text)
    return body[-1] if body else ""


def entry_lines(text):
    """Digest lines that are neither the trailing line nor a heading."""
    return [line for line in lines(text)[:-1] if line.strip().startswith("-")]


# ---------------------------------------------------------------------------
# viewer helpers (spec: `serve` Command, `/` Routes, `/catalog` Routes)
# ---------------------------------------------------------------------------

import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_VIEWER_HOST = "127.0.0.1"
DEFAULT_VIEWER_PORT = 8840

# The line `serve` prints once the listening socket is bound.
SERVE_URL_RE = re.compile(r"http://[^\s/]+")


def viewer_link(name, category, eid, host=DEFAULT_VIEWER_HOST,
                port=DEFAULT_VIEWER_PORT):
    """The viewer link format required for change reports."""
    return "http://%s:%s/catalog/%s/%s/%s" % (host, port, name, category, eid)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx responses to the caller instead of following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Response:
    def __init__(self, status, headers, body, url):
        self.status = status
        self.headers = headers
        self.body = body
        self.url = url

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    @property
    def location(self):
        return self.headers.get("Location")

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Response(status=%r, location=%r, body=%r)" % (
            self.status, self.location, self.body[:400]
        )


class ViewerClient:
    """One browser: a cookie jar plus helpers for the viewer's routes."""

    def __init__(self, base, jar=None):
        self.base = base.rstrip("/")
        self.jar = jar if jar is not None else http.cookiejar.CookieJar()
        cookies = urllib.request.HTTPCookieProcessor(self.jar)
        self.plain = urllib.request.build_opener(cookies, _NoRedirect)
        self.following = urllib.request.build_opener(cookies)

    def url(self, path):
        return self.base + path

    def _send(self, path, data=None, follow=False, method=None):
        request = urllib.request.Request(self.url(path), data=data,
                                         method=method)
        if data is not None:
            request.add_header("Content-Type",
                               "application/x-www-form-urlencoded")
        opener = self.following if follow else self.plain
        try:
            with opener.open(request, timeout=15) as response:
                return Response(response.status, response.headers,
                                response.read(), response.geturl())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            exc.close()
            return Response(exc.code, exc.headers, body, exc.url)

    def get(self, path, follow=False):
        return self._send(path, follow=follow)

    def post(self, path, fields=None, raw=None, follow=False):
        if raw is None:
            raw = urllib.parse.urlencode(fields or {})
        return self._send(path, data=raw.encode("utf-8"), follow=follow)

    # -- JSON-bodied annotation methods -------------------------------------

    def send_json(self, method, path, data=None, raw=None, follow=False):
        """Send `method path` with a JSON request body.

        `data` is serialized; `raw` (str/bytes) is sent verbatim so malformed
        bodies can be exercised. `raw=None` and `data=None` send no body.
        """
        if raw is None and data is None:
            payload = None
        else:
            payload = json.dumps(data) if raw is None else raw
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        request = urllib.request.Request(self.url(path), data=payload,
                                         method=method)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        opener = self.following if follow else self.plain
        try:
            with opener.open(request, timeout=15) as response:
                return Response(response.status, response.headers,
                                response.read(), response.geturl())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            exc.close()
            return Response(exc.code, exc.headers, body, exc.url)

    def create(self, path, data=None, raw=None, follow=False):
        return self.send_json("POST", path, data, raw, follow)

    def patch(self, path, data=None, raw=None, follow=False):
        return self.send_json("PATCH", path, data, raw, follow)

    def delete(self, path, data=None, raw=None, follow=False):
        return self.send_json("DELETE", path, data, raw, follow)

    def later_session(self):
        """A later session of the same browser: only stored cookies survive."""
        jar = http.cookiejar.CookieJar()
        for cookie in self.jar:
            if not cookie.discard:
                jar.set_cookie(cookie)
        return ViewerClient(self.base, jar)

    def other_browser(self):
        return ViewerClient(self.base)


def browser_stub(tmp_path, record="opened.txt"):
    """A fake `$BROWSER` that appends every URL it is handed to a file."""
    target = os.path.join(str(tmp_path), record)
    script = os.path.join(str(tmp_path), "fake-browser.sh")
    with open(script, "w") as fh:
        fh.write('#!/bin/sh\necho "$1" >> "' + target + '"\n')
    os.chmod(script, 0o755)
    return script, target


def wait_for_file(path, timeout=15.0):
    """Wait for `path` to hold at least one line, returning its contents."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(path):
            with open(path) as fh:
                text = fh.read()
            if text.strip():
                return text
        time.sleep(0.05)
    return ""


@pytest.fixture
def viewer(tmp_path):
    """Start `python mvault.py serve ...` and talk to it over HTTP.

    The server is a long-lived process, so its output goes to a log file
    rather than an undrained pipe; the log is also how the harness learns
    which port it actually bound.
    """
    started = []

    def start(*args, cwd=None, port=0, env=None, expect_ready=True):
        index = len(started)
        log_path = os.path.join(str(tmp_path), "serve-%d.log" % index)
        argv = [sys.executable, MVAULT, "serve", *[str(a) for a in args]]
        if port is not None:
            argv.append("--port=%d" % port)
        environ = dict(os.environ)
        environ.setdefault("MVAULT_NO_BROWSER", "1")
        environ.update(env or {})
        handle = open(log_path, "w")
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd or tmp_path),
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=environ,
            text=True,
        )
        started.append((proc, handle))
        if not expect_ready:
            return proc
        base = None
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            with open(log_path) as fh:
                text = fh.read()
            match = SERVE_URL_RE.search(text)
            if match:
                base = match.group(0)
                break
            time.sleep(0.05)
        if base is None:
            with open(log_path) as fh:
                raise AssertionError("serve did not start: %r" % fh.read())
        client = ViewerClient(base)
        client.proc = proc
        client.log_path = log_path
        return client

    yield start

    for proc, handle in started:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()
                proc.wait(timeout=10)
        handle.close()
