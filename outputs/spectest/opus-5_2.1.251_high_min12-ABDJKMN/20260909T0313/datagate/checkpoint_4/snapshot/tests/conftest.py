"""Shared fixtures: a local origin server that serves arbitrary bodies, and a
Flask test client bound to a freshly-emptied datagate store."""

import io
import os
import sys
import threading
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
