"""Spec section: TLS-aware endpoint URLs."""
import io
import urllib.parse
from urllib.parse import urlparse

import pytest

import datagate

CSV = "name,qty\nwidget,3\n"


def convert(client, url, host=None):
    query = "source=" + urllib.parse.quote(url, safe="")
    headers = {} if host is None else {"Host": host}
    return client.get("/convert", query_string=query, headers=headers)


def upload(client, host=None, body=CSV):
    headers = {} if host is None else {"Host": host}
    return client.post("/upload",
                       data={"file": (io.BytesIO(body.encode("utf-8")), "d.csv")},
                       content_type="multipart/form-data", headers=headers)


# =============================================================================
# Phrase: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints."
# Context: false is also the default, so this is the unchanged behaviour.
# =============================================================================

def test_convert_endpoint_is_relative_when_tls_is_off(make_app, origin):
    client = make_app(REQUIRE_TLS="false").test_client()
    url = origin.add(CSV)
    endpoint = convert(client, url).get_json()["endpoint"]
    assert endpoint == "/datasets/%s" % datagate.dataset_id(url)


def test_upload_endpoint_is_relative_when_tls_is_off(make_app):
    client = make_app(REQUIRE_TLS="false").test_client()
    endpoint = upload(client).get_json()["endpoint"]
    assert endpoint == "/datasets/%s" % datagate.upload_id(CSV.encode("utf-8"))


def test_relative_is_the_default(make_app, origin):
    client = make_app().test_client()
    assert convert(client, origin.add(CSV)).get_json()["endpoint"].startswith("/")


def test_relative_endpoint_has_no_scheme_or_host(make_app, origin):
    client = make_app(REQUIRE_TLS="0").test_client()
    endpoint = convert(client, origin.add(CSV)).get_json()["endpoint"]
    parts = urlparse(endpoint)
    assert parts.scheme == "" and parts.netloc == ""


def test_relative_endpoint_is_fetchable(make_app, origin):
    client = make_app(REQUIRE_TLS="no").test_client()
    endpoint = convert(client, origin.add(CSV)).get_json()["endpoint"]
    assert client.get(endpoint).status_code == 200


# =============================================================================
# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs
#          using request host."
# Context: the scheme is literally https and the authority is the request's Host.
# =============================================================================

def test_convert_endpoint_is_absolute_https_when_tls_is_on(make_app, origin):
    client = make_app(REQUIRE_TLS="true").test_client()
    url = origin.add(CSV)
    endpoint = convert(client, url, host="data.example.com").get_json()["endpoint"]
    assert endpoint == "https://data.example.com/datasets/%s" % datagate.dataset_id(url)


def test_upload_endpoint_is_absolute_https_when_tls_is_on(make_app):
    client = make_app(REQUIRE_TLS="true").test_client()
    endpoint = upload(client, host="data.example.com").get_json()["endpoint"]
    assert endpoint == ("https://data.example.com/datasets/%s"
                        % datagate.upload_id(CSV.encode("utf-8")))


def test_absolute_endpoint_uses_the_request_host(make_app, origin):
    client = make_app(REQUIRE_TLS="on").test_client()
    url = origin.add(CSV)
    for host in ("a.example", "b.example"):
        endpoint = convert(client, url, host=host).get_json()["endpoint"]
        assert urlparse(endpoint).hostname == host


def test_absolute_endpoint_keeps_the_hosts_port(make_app, origin):
    """"request host" is the Host header verbatim (AMBIGUITIES T74)."""
    client = make_app(REQUIRE_TLS="on").test_client()
    endpoint = convert(client, origin.add(CSV), host="h.example:8443").get_json()
    assert endpoint["endpoint"].startswith("https://h.example:8443/datasets/")


def test_scheme_is_https_even_though_the_request_arrived_over_http(make_app, origin):
    client = make_app(REQUIRE_TLS="1").test_client()
    endpoint = convert(client, origin.add(CSV), host="h.example").get_json()["endpoint"]
    assert endpoint.startswith("https://")


def test_absolute_endpoint_path_is_the_dataset_path(make_app, origin):
    client = make_app(REQUIRE_TLS="yes").test_client()
    url = origin.add(CSV)
    endpoint = convert(client, url, host="h.example").get_json()["endpoint"]
    assert urlparse(endpoint).path == "/datasets/%s" % datagate.dataset_id(url)


def test_the_dataset_is_reachable_at_that_path(make_app, origin):
    client = make_app(REQUIRE_TLS="yes").test_client()
    endpoint = convert(client, origin.add(CSV), host="h.example").get_json()["endpoint"]
    response = client.get(urlparse(endpoint).path)
    assert response.status_code == 200
    assert response.get_json()["columns"] == ["name", "qty"]


def test_plain_http_requests_are_still_served_when_tls_is_required(make_app, origin):
    """The setting rewrites endpoint URLs; it does not refuse requests (T74)."""
    client = make_app(REQUIRE_TLS="true").test_client()
    assert convert(client, origin.add(CSV)).status_code == 200


def test_tls_setting_does_not_change_other_responses(make_app, origin):
    """Only the `endpoint` string differs; a dataset read is byte-for-byte the same."""
    url = origin.add(CSV)
    on = make_app(REQUIRE_TLS="true").test_client()
    off = make_app(REQUIRE_TLS="false").test_client()
    path = urlparse(convert(on, url, host="h.example").get_json()["endpoint"]).path
    assert convert(off, url).get_json()["endpoint"] == path
    with_tls, without = on.get(path).get_json(), off.get(path).get_json()
    assert set(with_tls) == set(without)
    for key in set(with_tls) - {"query_ms"}:  # timing is the only free field
        assert with_tls[key] == without[key]


def test_export_response_is_unaffected_by_the_tls_setting(make_app, origin):
    client = make_app(REQUIRE_TLS="true").test_client()
    endpoint = convert(client, origin.add(CSV), host="h.example").get_json()["endpoint"]
    response = client.get(urlparse(endpoint).path + "/export")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")


def test_cached_convert_reply_uses_the_same_rule(make_app, origin):
    """A cache hit must produce the same absolute endpoint a fresh one would."""
    client = make_app(REQUIRE_TLS="true").test_client()
    url = origin.add(CSV)
    first = convert(client, url, host="h.example").get_json()["endpoint"]
    second = convert(client, url, host="h.example").get_json()["endpoint"]
    assert first == second and first.startswith("https://h.example/")
