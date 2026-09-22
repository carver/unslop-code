"""Shared fixtures: a datagate test client and a local origin server for sources."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from datagate_core.server import create_app


class OriginServer:
    """Local HTTP server that serves byte payloads registered by the tests."""

    def __init__(self, host, port):
        self._responses = {}
        self.base_url = f"http://{host}:{port}"

    def serve(self, path, body, status=200, content_type="text/csv"):
        """Register `body` (bytes or str) at `path` and return its absolute URL."""
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self._responses[path] = (status, content_type, payload)
        return f"{self.base_url}{path}"

    def url_for(self, path):
        return f"{self.base_url}{path}"

    def response_for(self, path):
        return self._responses.get(path)


@pytest.fixture(scope="session")
def origin():
    server_state = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            registered = server_state["origin"].response_for(self.path)
            if registered is None:
                self.send_error(404, "not registered")
                return
            status, content_type, payload = registered
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_state["origin"] = OriginServer(*httpd.server_address)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield server_state["origin"]
    httpd.shutdown()


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def convert(client, origin):
    """Serve `body` at a unique path, convert it, and return the parsed JSON."""
    counter = iter(range(1000))

    def _convert(body, query="", path=None, **serve_kwargs):
        url = origin.serve(path or f"/fixture-{next(counter)}.csv", body, **serve_kwargs)
        return client.get(f"/convert?source={url}{query}")

    return _convert


@pytest.fixture
def dataset(client, convert):
    """Convert `body` and return the parsed `/datasets/<id>` payload."""

    def _dataset(body, query="", dataset_query="", **serve_kwargs):
        converted = convert(body, query=query, **serve_kwargs)
        assert converted.status_code == 200, converted.get_json()
        endpoint = converted.get_json()["endpoint"]
        response = client.get(f"{endpoint}{dataset_query}")
        assert response.status_code == 200, response.get_json()
        return response.get_json()

    return _dataset


SIMPLE_CSV = "name,age\nada,36\ngrace,45\n"
