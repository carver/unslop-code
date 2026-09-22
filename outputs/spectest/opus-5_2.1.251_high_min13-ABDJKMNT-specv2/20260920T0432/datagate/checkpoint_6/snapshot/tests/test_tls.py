"""`REQUIRE_TLS`: the form of the endpoint `/convert` and `/upload` return."""

import io

BODY = "name,age\nada,36\n"


def convert(client, origin, path, **kwargs):
    source = origin.serve(path, BODY)
    return client.get("/convert", query_string={"source": source}, **kwargs)


def upload(client, **kwargs):
    return client.post(
        "/upload",
        data={"file": (io.BytesIO(BODY.encode()), "table.csv")},
        content_type="multipart/form-data",
        **kwargs,
    )


# Spec: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative
# endpoints."
# Context: the default configuration, on both ingestion routes.
def test_endpoints_are_relative_by_default(client, origin):
    converted = convert(client, origin, "/tls-relative.csv").get_json()["endpoint"]
    uploaded = upload(client).get_json()["endpoint"]
    assert converted.startswith("/datasets/")
    assert uploaded.startswith("/datasets/")


# Spec: "`REQUIRE_TLS=false`: ... return relative endpoints."
# Context: the setting spelled out rather than left at its default.
def test_explicit_false_keeps_endpoints_relative(configured_client, origin):
    client = configured_client(REQUIRE_TLS="false")
    assert convert(client, origin, "/tls-false.csv").get_json()["endpoint"].startswith(
        "/datasets/"
    )


# Spec: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using
# request host."
# Context: /convert under TLS, against the host the client addressed.
def test_convert_returns_an_absolute_https_endpoint(configured_client, origin):
    client = configured_client(REQUIRE_TLS="true")
    endpoint = convert(client, origin, "/tls-convert.csv", headers={"Host": "data.example.com"})
    assert endpoint.get_json()["endpoint"].startswith("https://data.example.com/datasets/")


# Spec: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs"
# Context: /upload is the other endpoint the rule names.
def test_upload_returns_an_absolute_https_endpoint(configured_client):
    client = configured_client(REQUIRE_TLS="true")
    endpoint = upload(client, headers={"Host": "data.example.com"}).get_json()["endpoint"]
    assert endpoint.startswith("https://data.example.com/datasets/")


# Spec: "absolute `https://` URLs using request host"
# Context: a `Host` carrying a port, which is part of the address the client
# used (T63).
def test_the_request_host_is_echoed_with_its_port(configured_client):
    client = configured_client(REQUIRE_TLS="true")
    endpoint = upload(client, headers={"Host": "localhost:8001"}).get_json()["endpoint"]
    assert endpoint.startswith("https://localhost:8001/datasets/")


# Spec: "same endpoints are absolute `https://` URLs"
# Context: only the form changes — the dataset behind the URL is the same one,
# and the URL still resolves to it.
def test_only_the_form_of_the_endpoint_changes(configured_client, origin, tmp_path):
    storage = str(tmp_path / "shared")
    plain = configured_client(STORAGE_DIR=storage)
    secured = configured_client(REQUIRE_TLS="on", STORAGE_DIR=storage)
    relative = convert(plain, origin, "/tls-same.csv").get_json()["endpoint"]
    absolute = convert(secured, origin, "/tls-same.csv").get_json()["endpoint"]
    assert absolute.endswith(relative)
    assert secured.get(absolute).get_json()["rows"] == [["ada", 36]]


# Spec: "### TLS-aware endpoint URLs"
# Context: the setting governs the URLs only; a plaintext request is still
# served under `REQUIRE_TLS=true` (T64).
def test_plaintext_requests_are_still_served(configured_client, origin):
    client = configured_client(REQUIRE_TLS="yes")
    assert convert(client, origin, "/tls-plain.csv").status_code == 200
