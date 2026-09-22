"""Shared fixtures: a controllable origin HTTP server + a live datagate server."""
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATAGATE = os.path.join(ROOT, "datagate.py")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_port(host, port, timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def port_is_free(host, port):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


# --------------------------------------------------------------------------
# Origin server: serves fixture payloads (bytes) with chosen status/content-type
# --------------------------------------------------------------------------
class Origin:
    def __init__(self):
        self.routes = {}
        self.hits = {}
        self.port = None

    @property
    def base(self):
        return "http://127.0.0.1:%d" % self.port

    def add(self, path, body, status=200, content_type="text/csv"):
        """Register a payload; returns its absolute URL."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        if not path.startswith("/"):
            path = "/" + path
        self.routes[path] = (status, content_type, body)
        return self.base + path

    def add_text(self, path, text, charset="utf-8", content_type=None):
        if content_type is None:
            content_type = "text/csv"
        return self.add(path, text.encode(charset), content_type=content_type)


class _Handler(http.server.BaseHTTPRequestHandler):
    origin = None
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        o = self.origin
        o.hits[path] = o.hits.get(path, 0) + 1
        if path not in o.routes:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        status, ctype, body = o.routes[path]
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def origin():
    o = Origin()
    handler = type("H", (_Handler,), {"origin": o})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    o.port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield o
    srv.shutdown()
    srv.server_close()


# --------------------------------------------------------------------------
# datagate server under test
# --------------------------------------------------------------------------
class Client:
    def __init__(self, base):
        self.base = base

    def raw(self, path, method="GET", headers=None, timeout=30):
        url = path if path.startswith("http") else self.base + path
        req = urllib.request.Request(url, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def get(self, path, **kw):
        """Returns (status, headers, parsed_json_or_None)."""
        status, headers, body = self.raw(path, **kw)
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = None
        return status, headers, data

    def json(self, path, **kw):
        return self.get(path, **kw)[2]

    def convert(self, source=None, charset=None, extra=""):
        from urllib.parse import quote
        q = []
        if source is not None:
            q.append("source=" + quote(source, safe=""))
        if charset is not None:
            q.append("charset=" + quote(charset, safe=""))
        qs = "&".join(q)
        if extra:
            qs = (qs + "&" + extra) if qs else extra
        return self.get("/convert" + ("?" + qs if qs else ""))


def _spawn(port, address="127.0.0.1", args=None, tag="server"):
    log = open(os.path.join(ROOT, "tests", "_%s.log" % tag), "ab")
    if args is None:
        args = ["start", "--port", str(port), "--address", address]
    proc = subprocess.Popen(
        [sys.executable, DATAGATE] + args,
        cwd=ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
    )
    return proc


@pytest.fixture(scope="session")
def server():
    port = free_port()
    proc = _spawn(port)
    assert wait_for_port("127.0.0.1", port), "datagate did not start"
    yield Client("http://127.0.0.1:%d" % port)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def csv_url(origin):
    """Register a CSV payload under a unique path; return its URL."""
    counter = {"n": 0}

    def make(body, name=None, status=200, content_type="text/csv"):
        counter["n"] += 1
        path = "/%s-%d.csv" % (name or "fixture", counter["n"])
        return origin.add(path, body, status=status, content_type=content_type)

    return make


@pytest.fixture
def dataset(server, csv_url):
    """Convert a CSV body and return the parsed /datasets/<id> payload."""
    def make(body, charset=None, name=None, content_type="text/csv", query=""):
        url = csv_url(body, name=name, content_type=content_type)
        status, _, data = server.convert(url, charset=charset)
        assert status == 200, data
        endpoint = data["endpoint"]
        s2, _, payload = server.get(endpoint + query)
        assert s2 == 200, payload
        return payload
    return make
