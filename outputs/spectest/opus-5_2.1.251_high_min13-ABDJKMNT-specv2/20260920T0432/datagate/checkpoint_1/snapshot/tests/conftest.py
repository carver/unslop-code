"""Shared fixtures: a Flask test client and a real local HTTP origin server.

The origin server lets the tests exercise the whole ingestion path (fetch,
decode, parse) against genuine HTTP responses instead of a mocked transport.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gateway.app import create_app


class _Origin:
    """A tiny HTTP server whose responses the tests register per path."""

    def __init__(self):
        self.responses = {}
        origin = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?")[0]
                if path not in origin.responses:
                    self.send_error(404)
                    return
                status, content_type, body = origin.responses[path]
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self):
        return self._server.server_address[1]

    def serve(self, path, body, status=200, content_type="text/csv"):
        """Register `body` (bytes or str) at `path` and return its full URL."""
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.responses[path] = (status, content_type, body)
        return self.url(path)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

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
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def convert(client, origin):
    """Serve a CSV body and run it through /convert, returning the response."""

    def _convert(body, path=None, params=None, **serve_kwargs):
        path = path or f"/fixture-{abs(hash((body, str(params)))):x}.csv"
        source = origin.serve(path, body, **serve_kwargs)
        query = {"source": source, **(params or {})}
        return client.get("/convert", query_string=query)

    return _convert


@pytest.fixture
def dataset(client, convert):
    """Convert a CSV body and return the parsed /datasets/<id> payload."""

    def _dataset(body, params=None, query=None, **serve_kwargs):
        endpoint = convert(body, params=params, **serve_kwargs).get_json()["endpoint"]
        return client.get(endpoint, query_string=query or {}).get_json()

    return _dataset
