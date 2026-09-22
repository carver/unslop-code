"""Shared fixtures: a fake origin web server, plus datagate under test."""
import csv
import http.server
import io
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
DATAGATE = ROOT / "datagate.py"
LOG_DIR = ROOT / ".test-logs"


def free_port():
    """Ask the OS for a port nobody is using, then release it."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --------------------------------------------------------------------------
# Fake remote origin holding the CSV files datagate will fetch.
# --------------------------------------------------------------------------
class OriginServer:
    def __init__(self):
        routes = self.routes = {}
        hits = self.hits = {}
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                with server.lock:
                    hits[path] = hits.get(path, 0) + 1
                entry = routes.get(path)
                if entry is None:
                    body = b"no such file\n"
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                status, content_type, body = entry
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # keep pytest output clean
                pass

        self.lock = threading.Lock()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def add(self, path, body, content_type="text/csv", status=200):
        """Register a file and return the URL datagate should be pointed at."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.routes[path] = (status, content_type, body)
        return self.url(path)

    def remove(self, path):
        """Stop serving a path; later GETs become remote 404s."""
        self.routes.pop(path, None)

    def hit_count(self, path):
        """How many times the origin has actually served (or 404ed) `path`."""
        with self.lock:
            return self.hits.get(path, 0)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(scope="session")
def origin():
    server = OriginServer()
    yield server
    server.stop()


# --------------------------------------------------------------------------
# datagate itself, run the way the spec says it is started.
# --------------------------------------------------------------------------
class Gate:
    def __init__(self, proc, address, port, log_path):
        self.proc = proc
        self.address = address
        self.port = port
        self.log_path = log_path

    @property
    def base(self):
        return f"http://{self.address}:{self.port}"

    def get(self, path, **kwargs):
        kwargs.setdefault("timeout", 30)
        return requests.get(self.base + path, **kwargs)

    def request(self, method, path, **kwargs):
        kwargs.setdefault("timeout", 30)
        return requests.request(method, self.base + path, **kwargs)

    def convert(self, **params):
        return self.get("/convert", params=params)

    def stop(self):
        if self.proc.poll() is None:
            # Single known PID -- never pkill by name.
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)


def start_gate(port=None, address=None, env=None, subcommand="start"):
    """Launch datagate; omit port/address to exercise the documented defaults."""
    LOG_DIR.mkdir(exist_ok=True)
    argv = [sys.executable, str(DATAGATE)]
    if subcommand:
        argv.append(subcommand)
    if port is not None:
        argv += ["--port", str(port)]
    if address is not None:
        argv += ["--address", address]

    log_path = LOG_DIR / f"datagate-{port or 'default'}-{int(time.time()*1000)}.log"
    log = open(log_path, "ab")  # long-lived process: log to a file, never a pipe
    child_env = dict(os.environ)
    child_env.setdefault("PYTHONUNBUFFERED", "1")
    if env:
        child_env.update(env)
    proc = subprocess.Popen(
        argv, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT), env=child_env
    )

    gate = Gate(proc, address or "127.0.0.1", port or 8001, log_path)
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"datagate exited with {proc.returncode}\n"
                + log_path.read_text(errors="replace")
            )
        try:
            gate.get("/datasets/readiness-probe", timeout=1)
            return gate
        except requests.RequestException:
            time.sleep(0.1)
    gate.stop()
    raise RuntimeError("datagate did not become ready\n" + log_path.read_text(errors="replace"))


def start_expecting_failure(env=None, port=None, subcommand="start", timeout=15):
    """Launch datagate expecting startup to fail; return (returncode, log text).

    Used for environment values the spec says must be rejected at startup. The
    child is waited on by PID -- never signalled by name.
    """
    LOG_DIR.mkdir(exist_ok=True)
    port = port or free_port()
    argv = [sys.executable, str(DATAGATE)]
    if subcommand:
        argv.append(subcommand)
    argv += ["--port", str(port), "--address", "127.0.0.1"]

    log_path = LOG_DIR / f"datagate-fail-{port}-{int(time.time()*1000)}.log"
    log = open(log_path, "ab")  # never an undrained pipe
    child_env = dict(os.environ)
    child_env.setdefault("PYTHONUNBUFFERED", "1")
    if env:
        child_env.update(env)
    proc = subprocess.Popen(
        argv, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT), env=child_env
    )
    try:
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()  # known PID, never pkill
        proc.wait(timeout=10)
        log.close()
        raise AssertionError(
            f"datagate kept running instead of failing startup\n"
            + log_path.read_text(errors="replace")
        )
    log.close()
    return returncode, log_path.read_text(errors="replace"), port


def port_is_closed(port, address="127.0.0.1"):
    """True when nothing is listening -- a failed startup must not have bound."""
    try:
        requests.get(f"http://{address}:{port}/datasets/x", timeout=2)
    except requests.RequestException:
        return True
    return False


@pytest.fixture(scope="session")
def gate():
    """The main long-lived server used by most tests."""
    g = start_gate(port=free_port(), address="127.0.0.1")
    yield g
    g.stop()


@pytest.fixture
def fresh_gate():
    """Factory for extra servers (defaults, restarts, environment tests)."""
    started = []

    def _start(**kwargs):
        g = start_gate(**kwargs)
        started.append(g)
        return g

    yield _start
    for g in started:
        g.stop()


# --------------------------------------------------------------------------
# Helpers shared across tests.
# --------------------------------------------------------------------------
def convert_ok(gate, source, **params):
    """Convert a source that is expected to succeed; return its dataset path."""
    resp = gate.convert(source=source, **params)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    return body["endpoint"]


def dataset(gate, source, **params):
    """Convert then query, returning the parsed dataset payload."""
    endpoint = convert_ok(gate, source, **params)
    resp = gate.get(endpoint)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------
# Spreadsheet builders (multi-format ingestion).
# --------------------------------------------------------------------------
def xlsx_bytes(sheets):
    """Build .xlsx bytes. `sheets` is [(title, [[cell, ...], ...]), ...]."""
    import openpyxl

    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets:
        sheet = book.create_sheet(title=title)
        for row in rows:
            sheet.append(list(row))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def xls_bytes(sheets):
    """Build legacy .xls bytes. `sheets` is [(title, [[cell, ...], ...]), ...]."""
    import xlwt

    book = xlwt.Workbook()
    for title, rows in sheets:
        sheet = book.add_sheet(title)
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                if cell is None:
                    continue
                sheet.write(r, c, cell)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def upload(gate, data, filename="table.csv", field="file", content_type=None, **params):
    """POST a multipart upload with the payload under `field`."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    files = {field: (filename, data, content_type or "application/octet-stream")}
    return gate.request("POST", "/upload", files=files, params=params or None)


def upload_ok(gate, data, **kwargs):
    """Upload a payload expected to succeed; return its dataset endpoint."""
    resp = upload(gate, data, **kwargs)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    return body["endpoint"]


def read_csv_text(text):
    """Parse an export body back into (header, rows) -- newline/quoting agnostic."""
    rows = [row for row in csv.reader(io.StringIO(text, newline="")) if row]
    return rows[0], rows[1:]


# --------------------------------------------------------------------------
# Configuration helpers (config file, allowlist, storage directory).
# --------------------------------------------------------------------------
def write_config(tmp_path, text, name="datagate.conf"):
    """Write a DATAGATE_CONFIG file and return its path as a string."""
    path = Path(tmp_path) / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def assert_error_envelope(resp, status):
    """The standard failure envelope: {"ok": false, "error": "<message>"}."""
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"]
    return body


def referer(host, path="/index.html", scheme="http"):
    """A Referer header value pointing at `host`."""
    return {"Referer": f"{scheme}://{host}{path}"}
