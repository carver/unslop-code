"""Spec tests for "TLS-aware endpoint URLs". Each section quotes its phrase."""
import urllib.parse

import pytest

from conftest import running

SIMPLE = "name,age\nada,36\n"


@pytest.fixture(scope="module")
def tls():
    """A server with `REQUIRE_TLS=true`."""
    with running({"REQUIRE_TLS": "true", "DATAGATE_CONFIG": None},
                 "tls_on") as client:
        yield client


@pytest.fixture(scope="module")
def plain():
    """A server with `REQUIRE_TLS=false`."""
    with running({"REQUIRE_TLS": "false", "DATAGATE_CONFIG": None},
                 "tls_off") as client:
        yield client


def upload(client, payload=SIMPLE, headers=None):
    status, _, data = client.upload(payload.encode("utf-8"), headers=headers)
    assert status == 200, data
    return data["endpoint"]


# ==========================================================================
# Spec: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints."
# ==========================================================================
def test_convert_returns_relative_endpoint(plain, csv_url):
    url = csv_url(SIMPLE, name="tls-off-convert")
    status, _, data = plain.convert(url)
    assert status == 200, data
    endpoint = data["endpoint"]
    assert endpoint.startswith("/datasets/")
    assert "://" not in endpoint


def test_upload_returns_relative_endpoint(plain):
    endpoint = upload(plain, "a,b\n1,2\n")
    assert endpoint.startswith("/datasets/")
    assert "://" not in endpoint


# Spec: `REQUIRE_TLS` defaults to `false`, so an unconfigured server is relative.
def test_default_is_relative(server, csv_url):
    url = csv_url(SIMPLE, name="tls-default")
    assert server.convert(url)[2]["endpoint"].startswith("/datasets/")


# The relative endpoint is usable as-is against the same server.
def test_relative_endpoint_is_fetchable(plain, csv_url):
    url = csv_url(SIMPLE, name="tls-off-usable")
    endpoint = plain.convert(url)[2]["endpoint"]
    status, _, payload = plain.get(endpoint)
    assert status == 200, payload
    assert payload["rows"] == [["ada", 36]]


# ==========================================================================
# Spec: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using
#        request host."
# ==========================================================================
def test_convert_returns_absolute_https_url(tls, csv_url):
    url = csv_url(SIMPLE, name="tls-on-convert")
    status, _, data = tls.convert(url)
    assert status == 200, data
    endpoint = data["endpoint"]
    assert endpoint.startswith("https://"), endpoint
    parts = urllib.parse.urlsplit(endpoint)
    assert parts.scheme == "https"
    assert parts.path.startswith("/datasets/")


def test_upload_returns_absolute_https_url(tls):
    endpoint = upload(tls, "a,b\n1,2\n")
    assert endpoint.startswith("https://"), endpoint
    assert urllib.parse.urlsplit(endpoint).path.startswith("/datasets/")


# Spec: "... using request host." — the host comes from the request itself.
def test_absolute_url_uses_the_request_host(tls):
    endpoint = upload(tls, "h,i\n1,2\n", headers={"Host": "datagate.example.org"})
    assert endpoint.startswith("https://datagate.example.org/datasets/")


def test_absolute_url_tracks_a_changing_host(tls):
    first = upload(tls, "h,i\n2,3\n", headers={"Host": "one.example"})
    second = upload(tls, "h,i\n2,3\n", headers={"Host": "two.example"})
    assert first.startswith("https://one.example/")
    assert second.startswith("https://two.example/")
    # Same bytes, same dataset: only the host part differs.
    assert urllib.parse.urlsplit(first).path == urllib.parse.urlsplit(second).path


# Spec: "using request host" — the host as sent, port included (AMBIGUITIES T92).
def test_absolute_url_keeps_the_request_port(tls):
    endpoint = upload(tls, "h,i\n3,4\n", headers={"Host": "app.example:8443"})
    assert endpoint.startswith("https://app.example:8443/datasets/")


# Spec: "same endpoints" — the dataset id is unchanged by the setting.
def test_same_dataset_id_under_both_settings(tls, plain, csv_url):
    url = csv_url(SIMPLE, name="tls-same-id")
    relative = plain.convert(url)[2]["endpoint"]
    absolute = tls.convert(url)[2]["endpoint"]
    assert urllib.parse.urlsplit(absolute).path == relative


# The path of the absolute URL still addresses the dataset on this server.
def test_absolute_endpoint_path_is_queryable(tls, csv_url):
    url = csv_url(SIMPLE, name="tls-on-usable")
    endpoint = tls.convert(url)[2]["endpoint"]
    path = urllib.parse.urlsplit(endpoint).path
    status, _, payload = tls.get(path)
    assert status == 200, payload
    assert payload["rows"] == [["ada", 36]]


# ==========================================================================
# Spec: the section is about endpoint URLs only (AMBIGUITIES T93)
# ==========================================================================
def test_require_tls_does_not_reject_plain_http_requests(tls, csv_url):
    """Every request in this module arrives over plain HTTP and is served."""
    url = csv_url(SIMPLE, name="tls-plain-http")
    assert tls.convert(url)[0] == 200
    assert tls.get("/datasets/unknown")[0] == 404


def test_dataset_and_export_responses_are_unchanged(tls, csv_url):
    url = csv_url(SIMPLE, name="tls-other-endpoints")
    path = urllib.parse.urlsplit(tls.convert(url)[2]["endpoint"]).path
    status, _, payload = tls.get(path)
    assert status == 200, payload
    assert set(payload) >= {"ok", "columns", "rows"}
    assert "endpoint" not in payload
    status, headers, body = tls.raw(path + "/export")
    assert status == 200
    assert b"ada" in body
