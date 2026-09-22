"""Fixtures: settings isolation, a test client, a file poster and a local HTTP server."""

import functools
import http.server
import io
import threading
from pathlib import Path

import pytest

from datagate.app import create_app
from datagate.config import CONFIG_VARIABLE, SETTINGS


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep each test's configuration to itself, storing datasets under tmp_path."""
    for name in (CONFIG_VARIABLE, *SETTINGS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))


@pytest.fixture
def client():
    return create_app().test_client()


@pytest.fixture
def configured_client(monkeypatch):
    """Return a factory building a client once the given settings are in the environment."""

    def build(**settings: str):
        for name, value in settings.items():
            monkeypatch.setenv(name, value)
        return create_app().test_client()

    return build


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
