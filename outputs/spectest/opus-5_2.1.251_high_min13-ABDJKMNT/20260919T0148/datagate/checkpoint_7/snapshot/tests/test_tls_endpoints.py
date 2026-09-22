"""Spec section: TLS-aware endpoint URLs -- the shape of the `endpoint` field."""

import pytest

from helpers import post_upload

CSV = "name,age\nada,36\n"


def convert(client, source, **kwargs):
    return client.get("/convert", query_string={"source": source}, **kwargs)


# Phrase: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints."
def test_convert_returns_a_relative_endpoint_by_default(settings_client, origin):
    client = settings_client()
    source = origin.serve("/data.csv", CSV)

    endpoint = convert(client, source).get_json()["endpoint"]

    assert endpoint.startswith("/datasets/")


# Phrase: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints."
def test_upload_returns_a_relative_endpoint_by_default(settings_client):
    client = settings_client(REQUIRE_TLS="false")

    assert post_upload(client, CSV).get_json()["endpoint"].startswith("/datasets/")


# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using
# request host."
def test_convert_returns_an_absolute_https_endpoint(settings_client, origin):
    client = settings_client(REQUIRE_TLS="true")
    source = origin.serve("/data.csv", CSV)

    endpoint = convert(client, source).get_json()["endpoint"]

    assert endpoint.startswith("https://localhost/datasets/")


# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs"
def test_upload_returns_an_absolute_https_endpoint(settings_client):
    client = settings_client(REQUIRE_TLS="on")

    assert post_upload(client, CSV).get_json()["endpoint"].startswith("https://localhost/datasets/")


# Phrase: "using request host"
@pytest.mark.parametrize("host", ["data.example.com", "gateway.internal"])
def test_the_absolute_url_uses_the_request_host(settings_client, origin, host):
    client = settings_client(REQUIRE_TLS="yes")
    source = origin.serve("/data.csv", CSV)

    endpoint = convert(client, source, headers={"Host": host}).get_json()["endpoint"]

    assert endpoint.startswith(f"https://{host}/datasets/")


# Phrase: "using request host"
# Context: the host includes the port the caller addressed (AMBIGUITIES T68).
def test_the_absolute_url_keeps_the_port(settings_client):
    client = settings_client(REQUIRE_TLS="1")

    response = post_upload(client, CSV, headers={"Host": "data.example.com:8443"})

    assert response.get_json()["endpoint"].startswith("https://data.example.com:8443/datasets/")


# Phrase: "same endpoints"
# Context: only the prefix changes; the dataset id is the same either way.
def test_only_the_prefix_changes(settings_client, origin):
    source = origin.serve("/data.csv", CSV)
    relative = convert(settings_client(REQUIRE_TLS="off"), source).get_json()["endpoint"]
    absolute = convert(settings_client(REQUIRE_TLS="on"), source).get_json()["endpoint"]

    assert absolute == "https://localhost" + relative


# Phrase: "`REQUIRE_TLS=true`"
# Context: the setting shapes the endpoint only; plaintext still works
# (AMBIGUITIES T69).
def test_a_plaintext_request_still_succeeds_under_require_tls(settings_client, origin):
    client = settings_client(REQUIRE_TLS="true")
    source = origin.serve("/data.csv", CSV)

    endpoint = convert(client, source).get_json()["endpoint"]

    assert client.get(endpoint).status_code == 200
