"""Shared fixtures: a test client plus helpers for serving fake remote CSVs."""

import pathlib
import sys

import pytest
import responses

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from datagate_app.server import create_app  # noqa: E402

SOURCE_URL = "https://example.test/data.csv"

SIMPLE_CSV = "name,age\nada,36\ngrace,45\n"


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def remote():
    """Intercept outbound HTTP so tests never touch the network."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def serve(remote):
    """Publish a body at a URL and hand back that URL."""

    def _serve(body, url=SOURCE_URL, content_type="text/csv", status=200):
        remote.add(responses.GET, url, body=body, status=status, content_type=content_type)
        return url

    return _serve


@pytest.fixture
def dataset(client, serve):
    """Convert a CSV body and return the parsed `/datasets/<id>` payload."""

    def _dataset(body, url=SOURCE_URL, content_type="text/csv", query=""):
        endpoint = client.get("/convert", query_string={"source": serve(body, url, content_type)})
        assert endpoint.status_code == 200, endpoint.get_json()
        return client.get(endpoint.get_json()["endpoint"] + query).get_json()

    return _dataset


@pytest.fixture
def endpoint(client, serve):
    """Convert a CSV body and hand back its `/datasets/<id>` path."""

    def _endpoint(body=SIMPLE_CSV, url=SOURCE_URL, content_type="text/csv"):
        response = client.get("/convert", query_string={"source": serve(body, url, content_type)})
        assert response.status_code == 200, response.get_json()
        return response.get_json()["endpoint"]

    return _endpoint


@pytest.fixture
def query(client, endpoint):
    """Request `/datasets/<id>` with a control query string and return the response."""

    def _query(query_string, body=SIMPLE_CSV, url=SOURCE_URL):
        return client.get(endpoint(body, url) + query_string)

    return _query
