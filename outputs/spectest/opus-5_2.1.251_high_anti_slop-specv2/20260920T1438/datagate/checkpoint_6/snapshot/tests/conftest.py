"""Fixtures: the datagate app plus a local HTTP server hosting fixture files."""

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gateway.app import create_app
from gateway.config import Settings


@pytest.fixture
def files() -> dict[str, bytes]:
    """Payloads served by the local server, keyed by request path."""
    return {}


@pytest.fixture
def downloads() -> list[str]:
    """Paths the local server has been asked for, in request order."""
    return []


@pytest.fixture
def base_url(files, downloads):
    """Run a throwaway HTTP server exposing ``files`` and yield its base URL."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            downloads.append(self.path)
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
def settings(tmp_path) -> Settings:
    """Default settings storing datasets in a directory of this test's own."""
    return Settings(storage_dir=tmp_path / "datasets")


@pytest.fixture
def client(settings):
    return create_app(settings).test_client()


@pytest.fixture
def convert(client, files, base_url):
    """Publish ``payload`` at ``/data.csv`` and convert it, returning the response."""

    def run(payload: bytes, **params):
        files["/data.csv"] = payload
        query = {"source": f"{base_url}/data.csv", **params}
        return client.get("/convert", query_string=query)

    return run


@pytest.fixture
def read(client, convert):
    """Convert ``payload``, then read it back with the given control parameters."""

    def run(payload: bytes, **controls):
        endpoint = convert(payload).get_json()["endpoint"]
        return client.get(endpoint, query_string=controls)

    return run


@pytest.fixture
def upload(client):
    """Post ``payload`` as a multipart upload and return the response."""

    def run(payload: bytes, field: str = "file", name: str = "data.csv", **params):
        return client.post(
            "/upload",
            data={field: (io.BytesIO(payload), name)},
            content_type="multipart/form-data",
            query_string=params,
        )

    return run
