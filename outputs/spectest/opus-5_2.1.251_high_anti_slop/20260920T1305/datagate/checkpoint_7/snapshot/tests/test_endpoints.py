"""Tests for the endpoint URLs /convert and /upload hand back under REQUIRE_TLS."""

import io

import pytest

CSV = b"name,age\nada,36\n"


@pytest.fixture
def convert(configured_client, serve):
    """Return a factory converting a source with REQUIRE_TLS set to the given value."""

    def run(require_tls: str):
        client = configured_client(REQUIRE_TLS=require_tls)
        return client.get("/convert", query_string={"source": serve("a.csv", CSV)})

    return run


def test_relative_endpoints_without_tls(convert):
    assert convert("false").json["endpoint"].startswith("/datasets/")


def test_absolute_https_endpoints_with_tls(convert):
    endpoint = convert("true").json["endpoint"]

    assert endpoint.startswith("https://localhost/datasets/")


def test_the_tls_endpoint_names_the_request_host(configured_client, serve):
    client = configured_client(REQUIRE_TLS="true")

    response = client.get(
        "/convert",
        query_string={"source": serve("a.csv", CSV)},
        headers={"Host": "datagate.example.com"},
    )

    assert response.json["endpoint"].startswith("https://datagate.example.com/datasets/")


def test_uploads_return_absolute_endpoints_with_tls(configured_client):
    client = configured_client(REQUIRE_TLS="on")

    response = client.post(
        "/upload",
        data={"file": (io.BytesIO(CSV), "a.csv")},
        content_type="multipart/form-data",
    )

    assert response.json["endpoint"].startswith("https://localhost/datasets/")


def test_the_tls_endpoint_stays_queryable(configured_client, serve):
    client = configured_client(REQUIRE_TLS="true")
    endpoint = client.get(
        "/convert", query_string={"source": serve("a.csv", CSV)}
    ).json["endpoint"]

    assert client.get(endpoint.removeprefix("https://localhost")).json["rows"] == [
        ["ada", 36]
    ]
