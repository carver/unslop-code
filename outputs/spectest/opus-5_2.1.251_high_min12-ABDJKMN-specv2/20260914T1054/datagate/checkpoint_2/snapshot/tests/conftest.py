"""Shared fixtures: a real local origin server for `source` URLs, plus a client for the app.

The spec's `/convert` fetches a *remote* CSV over HTTP, so the tests stand up a throwaway
HTTP origin on 127.0.0.1 and hand out real URLs into it. No outbound network is used.
"""
import http.server
import socket
import threading

import pytest

import datagate


class _OriginHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output clean, no undrained pipes
        pass

    def _route(self):
        return self.server.routes.get(self.path.split("?")[0])

    def do_GET(self):
        route = self._route()
        if route is None:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        status, content_type, body = route
        self.send_response(status)
        if content_type is not None:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()


class Origin:
    """Serves registered byte payloads and vends the URL for each."""

    def __init__(self):
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OriginHandler)
        self._server.routes = {}
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._n = 0

    def add(self, body, path=None, status=200, content_type="text/csv"):
        """Register a payload; returns the absolute URL that serves it."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        if path is None:
            self._n += 1
            path = "/f%d.csv" % self._n
        self._server.routes[path] = (status, content_type, body)
        return self.base + path

    def url_for(self, path):
        return self.base + path

    def shutdown(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture(scope="session")
def origin():
    o = Origin()
    yield o
    o.shutdown()


@pytest.fixture()
def app():
    application = datagate.create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def convert(client):
    """POST-free helper: GET /convert with query params, returning (status, json)."""

    def _convert(**params):
        query = {k: v for k, v in params.items() if v is not None}
        resp = client.get("/convert", query_string=query)
        return resp.status_code, resp.get_json()

    return _convert


@pytest.fixture()
def dataset(client, convert, origin):
    """Ingest a CSV body and return the parsed /datasets/<id> payload."""

    def _dataset(body, charset=None, query_string=None, content_type="text/csv"):
        url = origin.add(body, content_type=content_type)
        status, payload = convert(source=url, charset=charset)
        assert status == 200, payload
        resp = client.get(payload["endpoint"], query_string=query_string or {})
        return resp.status_code, resp.get_json()

    return _dataset


def unused_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
