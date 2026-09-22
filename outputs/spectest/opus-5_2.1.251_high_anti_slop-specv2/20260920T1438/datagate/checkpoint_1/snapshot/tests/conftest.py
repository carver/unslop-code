"""Fixtures: the datagate app plus a local HTTP server hosting fixture files."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gateway.app import create_app


@pytest.fixture
def files() -> dict[str, bytes]:
    """Payloads served by the local server, keyed by request path."""
    return {}


@pytest.fixture
def base_url(files):
    """Run a throwaway HTTP server exposing ``files`` and yield its base URL."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = files.get(self.path)
            self.send_response(200 if payload is not None else 404)
            self.end_headers()
            self.wfile.write(payload or b"missing")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def client():
    return create_app().test_client()


@pytest.fixture
def convert(client, files, base_url):
    """Publish ``payload`` at ``/data.csv`` and convert it, returning the response."""

    def run(payload: bytes, **params):
        files["/data.csv"] = payload
        query = {"source": f"{base_url}/data.csv", **params}
        return client.get("/convert", query_string=query)

    return run
