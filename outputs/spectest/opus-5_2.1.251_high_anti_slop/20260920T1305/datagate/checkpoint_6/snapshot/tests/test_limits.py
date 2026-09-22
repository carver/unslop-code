"""Tests for MAX_SOURCE_SIZE on /convert and /upload."""

import io

import pytest

CSV = b"name,age\nada,36\n"


@pytest.fixture
def post(configured_client):
    """Return a factory posting CSV bytes to /upload under a given size limit."""

    def upload(limit: str, payload: bytes = CSV):
        client = configured_client(MAX_SOURCE_SIZE=limit)
        return client.post(
            "/upload",
            data={"file": (io.BytesIO(payload), "a.csv")},
            content_type="multipart/form-data",
        )

    return upload


def test_a_source_at_the_limit_is_converted(configured_client, serve):
    client = configured_client(MAX_SOURCE_SIZE=str(len(CSV)))

    response = client.get("/convert", query_string={"source": serve("a.csv", CSV)})

    assert response.status_code == 200
    assert response.json["ok"] is True


def test_a_source_over_the_limit_is_rejected(configured_client, serve):
    client = configured_client(MAX_SOURCE_SIZE=str(len(CSV) - 1))

    response = client.get("/convert", query_string={"source": serve("a.csv", CSV)})

    assert response.status_code == 400
    assert response.json["ok"] is False
    assert isinstance(response.json["error"], str)


def test_an_unset_limit_accepts_any_source(client, serve):
    response = client.get("/convert", query_string={"source": serve("a.csv", CSV * 500)})

    assert response.status_code == 200


def test_an_upload_at_the_limit_is_accepted(post):
    response = post(str(len(CSV)))

    assert response.status_code == 200
    assert response.json["ok"] is True


def test_an_upload_over_the_limit_is_rejected(post):
    response = post(str(len(CSV) - 1))

    assert response.status_code == 400
    assert response.json["ok"] is False


def test_an_oversized_source_is_not_stored(configured_client, serve):
    client = configured_client(MAX_SOURCE_SIZE="1")
    source = serve("a.csv", CSV)

    client.get("/convert", query_string={"source": source})
    repeated = client.get("/convert", query_string={"source": source})

    assert repeated.status_code == 400
