"""Spec section: TLS-aware endpoint URLs.

    `REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints.
    `REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using
    request host.
"""

import re

import pytest

SIMPLE = "name,age\nalice,30\nbob,41\n"
ENDPOINT_RE = re.compile(r"^/datasets/[^/]+$")


# Phrase: "`REQUIRE_TLS=false`: `/convert` ... return relative endpoints."
def test_convert_endpoint_is_relative_when_tls_not_required(configure, convert):
    assert configure(REQUIRE_TLS="false") is None
    endpoint = convert("/tls-off.csv", SIMPLE).get_json()["endpoint"]
    assert ENDPOINT_RE.match(endpoint), endpoint


# Phrase: "`REQUIRE_TLS=false`: ... `/upload` return relative endpoints."
def test_upload_endpoint_is_relative_when_tls_not_required(configure, client, upload):
    assert configure(REQUIRE_TLS="false") is None
    endpoint = upload(SIMPLE).get_json()["endpoint"]
    assert ENDPOINT_RE.match(endpoint), endpoint


# Phrase: "`REQUIRE_TLS` | boolean | `false`" -- the default is the relative form.
def test_endpoint_is_relative_by_default(configure, convert):
    assert configure() is None
    endpoint = convert("/tls-default.csv", SIMPLE).get_json()["endpoint"]
    assert ENDPOINT_RE.match(endpoint), endpoint


# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs
# using request host."  (/convert)
def test_convert_endpoint_is_absolute_https_when_tls_required(configure, client, origin):
    assert configure(REQUIRE_TLS="true") is None
    origin.add("/tls-on.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/tls-on.csv")},
                          headers={"Host": "gate.example.com"})
    assert response.status_code == 200, response.get_data(as_text=True)
    endpoint = response.get_json()["endpoint"]
    assert endpoint.startswith("https://gate.example.com/datasets/"), endpoint


# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs
# using request host."  (/upload)
def test_upload_endpoint_is_absolute_https_when_tls_required(configure, client, upload):
    assert configure(REQUIRE_TLS="true") is None
    response = upload(SIMPLE, headers={"Host": "gate.example.com"})
    assert response.status_code == 200, response.get_data(as_text=True)
    endpoint = response.get_json()["endpoint"]
    assert endpoint.startswith("https://gate.example.com/datasets/"), endpoint


# Phrase: "same endpoints" -- only the prefix changes; the dataset id and path
# are the same under both settings.
def test_only_the_prefix_changes(configure, client, origin):
    origin.add("/tls-same.csv", SIMPLE)
    source = origin.url("/tls-same.csv")

    assert configure(REQUIRE_TLS="false") is None
    relative = client.get("/convert", query_string={"source": source}).get_json()["endpoint"]

    assert configure(REQUIRE_TLS="true") is None
    absolute = client.get("/convert", query_string={"source": source},
                          headers={"Host": "h.example"}).get_json()["endpoint"]

    assert absolute == "https://h.example" + relative


# Phrase: "using request host" -- the host comes from the request, not from a
# fixed configured value, and the port is kept (AMBIGUITIES T75).
@pytest.mark.parametrize("host", ["one.example", "two.example:8443", "127.0.0.1:8001"])
def test_absolute_url_uses_the_request_host(configure, client, upload, host):
    assert configure(REQUIRE_TLS="true") is None
    endpoint = upload(SIMPLE, headers={"Host": host}).get_json()["endpoint"]
    assert endpoint.startswith("https://{}/datasets/".format(host)), endpoint


# Phrase: "`REQUIRE_TLS=true`" -- the returned absolute endpoint still names a
# working dataset: its path resolves on this server.
def test_absolute_endpoint_path_resolves(configure, client, upload):
    assert configure(REQUIRE_TLS="true") is None
    endpoint = upload(SIMPLE, headers={"Host": "h.example"}).get_json()["endpoint"]
    path = endpoint.split("h.example", 1)[1]
    payload = client.get(path).get_json()
    assert payload["ok"] is True
    assert payload["columns"] == ["name", "age"]


# Phrase: "`REQUIRE_TLS=true`" applies to a cache hit exactly as to a fresh
# parse -- the second /convert returns the same absolute endpoint.
def test_cached_convert_also_returns_the_absolute_form(configure, client, origin):
    assert configure(REQUIRE_TLS="true", CACHE_ENABLED="true") is None
    origin.add("/tls-cache.csv", SIMPLE)
    source = origin.url("/tls-cache.csv")
    headers = {"Host": "h.example"}
    first = client.get("/convert", query_string={"source": source}, headers=headers)
    second = client.get("/convert", query_string={"source": source}, headers=headers)
    assert first.get_json()["endpoint"] == second.get_json()["endpoint"]
    assert second.get_json()["endpoint"].startswith("https://h.example/datasets/")


# Phrase: "TLS-aware endpoint URLs" -- REQUIRE_TLS only shapes the endpoint
# string; a plain-HTTP request is still served and an http:// source is still
# ingested (AMBIGUITIES T76).
def test_require_tls_does_not_reject_plain_http(configure, client, origin):
    assert configure(REQUIRE_TLS="true") is None
    origin.add("/tls-plain.csv", SIMPLE)  # an http:// source
    response = client.get("/convert",
                          query_string={"source": origin.url("/tls-plain.csv")})
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "TLS-aware endpoint URLs" -- other responses are unaffected: the
# dataset payload gains no endpoint field either way.
def test_dataset_payload_is_unchanged_by_require_tls(configure, client, upload):
    assert configure(REQUIRE_TLS="true") is None
    endpoint = upload(SIMPLE, headers={"Host": "h.example"}).get_json()["endpoint"]
    payload = client.get(endpoint.split("h.example", 1)[1]).get_json()
    assert set(payload) == {"ok", "columns", "rows", "total", "query_ms"}


# Phrase: "`REQUIRE_TLS=true`" set through the config file behaves identically.
def test_require_tls_from_the_config_file(configure, config_file, client, upload):
    assert configure(DATAGATE_CONFIG=config_file("REQUIRE_TLS=on\n")) is None
    endpoint = upload(SIMPLE, headers={"Host": "h.example"}).get_json()["endpoint"]
    assert endpoint.startswith("https://h.example/datasets/"), endpoint
