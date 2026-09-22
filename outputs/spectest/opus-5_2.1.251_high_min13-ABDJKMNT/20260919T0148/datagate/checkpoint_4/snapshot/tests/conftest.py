"""Shared fixtures: a Flask test client and a local origin server for CSV bytes."""

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from datagate_core.server import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return app.test_client()


class Origin:
    """A throwaway HTTP server that serves registered byte payloads."""

    def __init__(self, host, port):
        self._base = f"http://{host}:{port}"
        self.routes = {}

    def serve(self, path, body, status=200, content_type="text/csv"):
        """Register `body` (str or bytes) at `path` and return its absolute URL."""
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.routes[path] = (status, content_type, payload)
        return self.url(path)

    def url(self, path):
        return self._base + path


@pytest.fixture()
def origin():
    served = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - name mandated by BaseHTTPRequestHandler
            entry = served.get(self.path)
            if entry is None:
                self.send_error(404)
                return
            status, content_type, payload = entry
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            """Silence the default stderr access log."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    site = Origin(*server.server_address)
    site.routes = served
    yield site

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture()
def dataset(client, origin):
    """Serve a body from the origin, convert it and hand back its endpoint path."""

    def convert(body, path="/data.csv", **serve_kwargs):
        source = origin.serve(path, body, **serve_kwargs)
        response = client.get("/convert", query_string={"source": source})
        assert response.status_code == 200, response.get_json()
        return response.get_json()["endpoint"]

    return convert


@pytest.fixture()
def converted(client, dataset):
    """Convert a CSV body and hand back the parsed `/datasets/<id>` payload."""

    def convert(body, query="", **serve_kwargs):
        return client.get(dataset(body, **serve_kwargs) + query)

    return convert


@pytest.fixture()
def upload(client):
    """POST a multipart body carrying `payload` under `field`."""

    def post(payload, field="file", filename="data.csv"):
        body = payload.encode("utf-8") if isinstance(payload, str) else payload
        return client.post(
            "/upload",
            data={field: (io.BytesIO(body), filename)},
            content_type="multipart/form-data",
        )

    return post
