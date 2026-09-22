"""Fixtures: a datagate test client, a file-posting helper, and a local HTTP server."""

import functools
import http.server
import io
import threading
from pathlib import Path

import pytest

from datagate.app import create_app


@pytest.fixture
def client():
    return create_app().test_client()


@pytest.fixture
def upload(client):
    """Return a factory that posts bytes to /upload as a named multipart file field."""

    def post(payload: bytes, name: str = "data.csv", field: str = "file"):
        return client.post(
            "/upload",
            data={field: (io.BytesIO(payload), name)},
            content_type="multipart/form-data",
        )

    return post


@pytest.fixture
def serve(tmp_path):
    """Return a factory that publishes bytes at a URL on a throwaway local server."""
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def publish(name: str, payload: bytes) -> str:
        Path(tmp_path, name).write_bytes(payload)
        return f"http://127.0.0.1:{server.server_port}/{name}"

    yield publish
    server.shutdown()
