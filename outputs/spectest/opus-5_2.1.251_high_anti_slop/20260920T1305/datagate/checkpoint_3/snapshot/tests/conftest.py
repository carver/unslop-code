"""Fixtures: a datagate test client and a local HTTP server that serves fixture files."""

import functools
import http.server
import threading
from pathlib import Path

import pytest

from datagate.app import create_app


@pytest.fixture
def client():
    return create_app().test_client()


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
