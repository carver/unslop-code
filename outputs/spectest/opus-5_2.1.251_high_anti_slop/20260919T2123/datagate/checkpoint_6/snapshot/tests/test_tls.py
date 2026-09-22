"""Tests for `REQUIRE_TLS`, which decides how ingestion endpoints report a dataset's URL."""

import pytest

from conftest import FIXTURES
from helpers import convert, upload


@pytest.fixture
def tls_client(make_client):
    return make_client(require_tls=True)


def test_relative_endpoints_without_required_tls(client, base_url):
    assert convert(client, base_url, "basic.csv").get_json()["endpoint"].startswith("/datasets/")
    assert upload(client, FIXTURES["staff.csv"]).get_json()["endpoint"].startswith("/datasets/")


def test_converted_endpoints_are_absolute_https_urls(tls_client, base_url):
    endpoint = convert(tls_client, base_url, "basic.csv").get_json()["endpoint"]
    assert endpoint.startswith("https://localhost/datasets/")


def test_uploaded_endpoints_are_absolute_https_urls(tls_client):
    endpoint = upload(tls_client, FIXTURES["staff.csv"]).get_json()["endpoint"]
    assert endpoint.startswith("https://localhost/datasets/")


def test_the_url_uses_the_requested_host(tls_client, base_url):
    response = tls_client.get(
        "/convert",
        query_string={"source": f"{base_url}/basic.csv"},
        headers={"Host": "data.example.com:8443"},
    )
    assert response.get_json()["endpoint"].startswith("https://data.example.com:8443/datasets/")


def test_the_absolute_url_addresses_the_same_dataset(tls_client, base_url):
    absolute = convert(tls_client, base_url, "basic.csv").get_json()["endpoint"]
    path = absolute.removeprefix("https://localhost")
    assert tls_client.get(path).get_json()["columns"] == ["name", "age", "score", "start"]
