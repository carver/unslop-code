"""Spec section: TLS-aware endpoint URLs."""

import io

from conftest import SIMPLE_CSV, SOURCE_URL


def convert(client, **headers):
    return client.get("/convert", query_string={"source": SOURCE_URL}, headers=headers)


def upload(client, **headers):
    payload = {"file": (io.BytesIO(SIMPLE_CSV.encode()), "data.csv")}
    return client.post("/upload", data=payload, content_type="multipart/form-data", headers=headers)


# Phrase: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints."
def test_convert_returns_a_relative_endpoint_by_default(client, serve):
    serve(SIMPLE_CSV)

    assert convert(client).get_json()["endpoint"].startswith("/datasets/")


# Phrase: "`REQUIRE_TLS=false`: ... `/upload` return relative endpoints."
def test_upload_returns_a_relative_endpoint_by_default(client):
    assert upload(client).get_json()["endpoint"].startswith("/datasets/")


# Phrase: "`REQUIRE_TLS=false`" (context: explicitly false is the same as unset)
def test_explicit_false_keeps_endpoints_relative(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(REQUIRE_TLS="false")

    assert convert(client).get_json()["endpoint"].startswith("/datasets/")


# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using request host."
def test_convert_returns_an_absolute_https_endpoint(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(REQUIRE_TLS="true")

    endpoint = convert(client, Host="data.example.com").get_json()["endpoint"]

    assert endpoint.startswith("https://data.example.com/datasets/")


# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs ..." (context: /upload)
def test_upload_returns_an_absolute_https_endpoint(configured):
    client = configured(REQUIRE_TLS="true")

    endpoint = upload(client, Host="data.example.com").get_json()["endpoint"]

    assert endpoint.startswith("https://data.example.com/datasets/")


# Phrase: "... using request host." (context: the host carries a port)
def test_absolute_endpoint_keeps_the_request_host_port(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(REQUIRE_TLS="true")

    endpoint = convert(client, Host="data.example.com:8443").get_json()["endpoint"]

    assert endpoint.startswith("https://data.example.com:8443/datasets/")


# Phrase: "same endpoints" (context: only the prefix changes, the dataset id does not)
def test_tls_changes_only_the_prefix(configured, serve, client):
    serve(SIMPLE_CSV)
    relative = convert(client).get_json()["endpoint"]

    tls = configured(REQUIRE_TLS="on")
    absolute = convert(tls, Host="localhost").get_json()["endpoint"]

    assert absolute == "https://localhost" + relative


# Phrase: "`REQUIRE_TLS=true`" (context: T67 -- the advertised endpoint still answers over the test client)
def test_absolute_endpoint_path_is_queryable(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(REQUIRE_TLS="true")

    endpoint = convert(client, Host="localhost").get_json()["endpoint"]

    assert client.get(endpoint.removeprefix("https://localhost")).status_code == 200
