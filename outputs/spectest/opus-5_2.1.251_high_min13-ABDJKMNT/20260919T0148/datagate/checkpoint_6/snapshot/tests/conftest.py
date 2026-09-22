"""Shared fixtures: a Flask test client and a local origin server for CSV bytes."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from helpers import post_upload

from datagate_core.config import SETTING_NAMES, CONFIG_VARIABLE
from datagate_core.server import create_app


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Start every test from the built-in defaults, storing datasets under `tmp_path`.

    Without this an inherited `DATAGATE_CONFIG` or `STORAGE_DIR` would leak between
    tests, and the default storage directory would accumulate in the working tree.
    """
    for name in (CONFIG_VARIABLE, *SETTING_NAMES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))


@pytest.fixture()
def settings_client(monkeypatch):
    """Build a client whose app read the given settings from the environment."""

    def build(**settings):
        for name, value in settings.items():
            monkeypatch.setenv(name, value)
        return create_app().test_client()

    return build


@pytest.fixture()
def config_file(monkeypatch, tmp_path):
    """Write a `DATAGATE_CONFIG` file and point the environment at it."""

    def write(text, name="datagate.conf"):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv(CONFIG_VARIABLE, str(path))
        return path

    return write


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return app.test_client()


class Origin:
    """A throwaway HTTP server that serves registered byte payloads.

    `hits` records every path fetched, in order, so caching tests can assert that
    a second `/convert` did not reach the network.
    """

    def __init__(self, host, port):
        self._base = f"http://{host}:{port}"
        self.routes = {}
        self.hits = []

    def downloads(self, path):
        """How many times `path` has been fetched since the server started."""
        return self.hits.count(path)

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
    fetched = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - name mandated by BaseHTTPRequestHandler
            fetched.append(self.path)
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
    site.hits = fetched
    yield site

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture()
def configured_client(monkeypatch):
    """Build a client whose app read a particular `CACHE_ENABLED` at startup."""

    def build(cache_enabled=None):
        if cache_enabled is None:
            monkeypatch.delenv("CACHE_ENABLED", raising=False)
        else:
            monkeypatch.setenv("CACHE_ENABLED", cache_enabled)
        return create_app().test_client()

    return build


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
        return post_upload(client, payload, field, filename)

    return post
