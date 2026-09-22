"""The ``MAX_SOURCE_SIZE`` ceiling, on ``/convert`` and on ``/upload`` alike."""

import io
from dataclasses import replace

import pytest

from gateway.app import create_app
from gateway.store import dataset_id, upload_origin

TABLE = b"name,age\nada,36\n"


@pytest.fixture
def service(settings, files, base_url):
    """Build a client under a maximum source size, reachable by either route."""

    class Service:
        def __init__(self, limit: int | None) -> None:
            self.client = create_app(
                replace(settings, max_source_size=limit)
            ).test_client()

        def convert(self, payload: bytes):
            files["/data.csv"] = payload
            return self.client.get(
                "/convert", query_string={"source": f"{base_url}/data.csv"}
            )

        def upload(self, payload: bytes):
            return self.client.post(
                "/upload",
                data={"file": (io.BytesIO(payload), "data.csv")},
                content_type="multipart/form-data",
            )

    return Service


@pytest.fixture(params=["convert", "upload"])
def ingest(request, service):
    """Send a payload to one of the two ingesting routes, under ``limit``."""

    def run(payload: bytes, limit: int | None):
        return getattr(service(limit), request.param)(payload)

    return run


def test_a_source_of_exactly_the_limit_is_accepted(ingest):
    response = ingest(TABLE, len(TABLE))
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_a_source_over_the_limit_is_refused(ingest):
    response = ingest(TABLE, len(TABLE) - 1)

    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert str(len(TABLE) - 1) in body["error"]


def test_an_unset_limit_accepts_any_size(ingest):
    big = b"name,age\n" + b"ada,36\n" * 10_000
    assert ingest(big, None).status_code == 200


def test_a_refused_source_is_not_stored(service):
    assert service(1).upload(TABLE).status_code == 400

    identifier = dataset_id(upload_origin(TABLE))
    assert service(None).client.get(f"/datasets/{identifier}").status_code == 404
