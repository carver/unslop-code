"""Shared fixtures: a local origin server that serves arbitrary bodies, and a
Flask test client bound to a freshly-emptied datagate store."""

import io
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datagate  # noqa: E402


class _Origin:
    """A tiny HTTP server used as the "remote" CSV host in tests."""

    def __init__(self):
        self._routes = {}
        self.hits = {}
        handler = self._make_handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.host, self.port = self._server.server_address[:2]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _make_handler(self):
        origin = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802
                path = self.path.split("?")[0]
                origin.hits[path] = origin.hits.get(path, 0) + 1
                entry = origin._routes.get(path)
                if entry is None:
                    body = b"not found"
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                body, content_type, status, extra = entry
                self.send_response(status)
                if content_type is not None:
                    self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # silence stderr logging
                pass

        return Handler

    def add(self, path, body, content_type="text/csv", status=200, headers=None):
        """Register `path`; `body` may be str (encoded utf-8) or bytes."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        self._routes[path] = (body, content_type, status, headers)
        return self.url(path)

    def url(self, path):
        return "http://{}:{}{}".format(self.host, self.port, path)

    def dead_url(self, path="/gone.csv"):
        """A URL on a port with nothing listening -> connection refused."""
        import socket

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return "http://127.0.0.1:{}{}".format(port, path)

    def shutdown(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture(scope="session")
def origin():
    server = _Origin()
    yield server
    server.shutdown()


@pytest.fixture
def client():
    datagate.reset_store()
    datagate.app.config["TESTING"] = True
    with datagate.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def convert(client, origin):
    """Register a CSV body on the origin and ingest it; returns the JSON body."""

    def _convert(path, body, params=None, **kwargs):
        origin.add(path, body, **kwargs)
        query = {"source": origin.url(path)}
        query.update(params or {})
        return client.get("/convert", query_string=query)

    return _convert


@pytest.fixture
def dataset(convert, client):
    """Ingest a CSV and return the parsed /datasets/<id> payload."""

    def _dataset(path, body, params=None, query=None, **kwargs):
        response = convert(path, body, params=params, **kwargs)
        assert response.status_code == 200, response.get_data(as_text=True)
        endpoint = response.get_json()["endpoint"]
        return client.get(endpoint, query_string=query or {})

    return _dataset


# ---------------------------------------------------------------------------
# Spreadsheet fixture builders (spec section: Multi-Format Ingestion)
# ---------------------------------------------------------------------------


def build_xlsx(sheets):
    """Build .xlsx bytes. `sheets` is [(name, [[cell, ...], ...]), ...]."""
    import openpyxl

    workbook = openpyxl.Workbook()
    first = True
    for name, rows in sheets:
        if first:
            sheet = workbook.active
            sheet.title = name
            first = False
        else:
            sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_xls(sheets):
    """Build legacy .xls (BIFF8) bytes. Same shape as `build_xlsx`."""
    import xlwt

    workbook = xlwt.Workbook()
    for name, rows in sheets:
        sheet = workbook.add_sheet(name)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if value is None:
                    continue
                sheet.write(r, c, value)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def xlsx():
    return build_xlsx


@pytest.fixture
def xls():
    return build_xls


@pytest.fixture
def upload(client):
    """POST bytes to /upload as multipart under `field` (default "file")."""

    def _upload(content, filename="data.csv", field="file", extra=None, **kwargs):
        if isinstance(content, str):
            content = content.encode("utf-8")
        data = {} if content is None else {field: (io.BytesIO(content), filename)}
        data.update(extra or {})
        return client.post("/upload", data=data, content_type="multipart/form-data",
                           **kwargs)

    return _upload


@pytest.fixture
def uploaded(upload, client):
    """Upload bytes and return the parsed /datasets/<id> response."""

    def _uploaded(content, filename="data.csv", query=None, **kwargs):
        response = upload(content, filename=filename, **kwargs)
        assert response.status_code == 200, response.get_data(as_text=True)
        endpoint = response.get_json()["endpoint"]
        return client.get(endpoint, query_string=query or {})

    return _uploaded


# ---------------------------------------------------------------------------
# Out-of-process server (spec sections: startup / command line, CACHE_ENABLED)
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATAGATE = os.path.join(ROOT, "datagate.py")
LOG_DIR = os.path.join(ROOT, ".test-logs")


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Server:
    """Runs `python datagate.py start ...` as a child process.

    Output goes to a log file rather than an undrained pipe, and the process is
    stopped by its own PID (never a pattern-based kill)."""

    def __init__(self, args, name, env=None):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_path = os.path.join(LOG_DIR, "{}.log".format(name))
        self._log = open(self.log_path, "wb")
        child_env = dict(os.environ)
        # A stray CACHE_ENABLED in the ambient environment must not leak into a
        # test that means to exercise the default.
        child_env.pop("CACHE_ENABLED", None)
        child_env.update(env or {})
        self.proc = subprocess.Popen(
            [sys.executable, DATAGATE, "start"] + list(args),
            cwd=ROOT,
            env=child_env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )

    def wait_until_listening(self, address, port, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(
                    "datagate exited early ({}); log:\n{}".format(
                        self.proc.returncode, self.log()
                    )
                )
            try:
                with socket.create_connection((address, port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    def wait_for_exit(self, timeout=20.0):
        """Return the exit status, or None if the process is still running."""
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def log(self):
        try:
            with open(self.log_path) as handle:
                return handle.read()
        except OSError:
            return ""

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()  # single known PID, not a pattern match
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._log.close()


@pytest.fixture
def server():
    started = []

    def _start(*args, name="datagate", env=None):
        instance = _Server(args, name, env=env)
        started.append(instance)
        return instance

    yield _start
    for instance in started:
        instance.stop()


def http_get(address, port, path, timeout=10.0):
    """Minimal HTTP GET so out-of-process tests do not depend on the app's client."""
    with socket.create_connection((address, port), timeout=timeout) as sock:
        message = "GET {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n".format(
            path, address, port
        )
        sock.sendall(message.encode("ascii"))
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].split()[1])
    return status, body.decode("utf-8", "replace")
