"""Spec section: TLS-aware endpoint URLs."""
from urllib.parse import urlparse

import pytest

from conftest import free_port, upload, write_config

A = "city,pop\nOslo,700000\n"


# ---------------------------------------------------------------------------
# Phrase: "`REQUIRE_TLS` | boolean | `false`"
# Context: the documented default, with nothing configured.
# ---------------------------------------------------------------------------
def test_require_tls_defaults_to_false(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1")
    url = origin.add("/tls-default.csv", A)
    endpoint = gate.convert(source=url).json()["endpoint"]
    assert endpoint.startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints."
# Context: /convert with TLS explicitly off.
# ---------------------------------------------------------------------------
def test_convert_returns_a_relative_endpoint_when_tls_is_off(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": "false"})
    url = origin.add("/tls-off-convert.csv", A)
    endpoint = gate.convert(source=url).json()["endpoint"]
    assert endpoint.startswith("/datasets/")
    assert urlparse(endpoint).scheme == ""
    assert urlparse(endpoint).netloc == ""


# ---------------------------------------------------------------------------
# Phrase: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints."
# Context: /upload with TLS explicitly off.
# ---------------------------------------------------------------------------
def test_upload_returns_a_relative_endpoint_when_tls_is_off(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": "false"})
    endpoint = upload(gate, A).json()["endpoint"]
    assert endpoint.startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs
#          using request host."
# Context: /convert with TLS on; the host is the one the client addressed.
# ---------------------------------------------------------------------------
def test_convert_returns_an_absolute_https_url_when_tls_is_on(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": "true"})
    url = origin.add("/tls-on-convert.csv", A)
    endpoint = gate.convert(source=url).json()["endpoint"]
    parts = urlparse(endpoint)
    assert parts.scheme == "https"
    assert parts.netloc == f"127.0.0.1:{gate.port}"
    assert parts.path.startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs ..."
# Context: /upload with TLS on.
# ---------------------------------------------------------------------------
def test_upload_returns_an_absolute_https_url_when_tls_is_on(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": "true"})
    endpoint = upload(gate, A).json()["endpoint"]
    assert endpoint == f"https://127.0.0.1:{gate.port}" + urlparse(endpoint).path
    assert urlparse(endpoint).path.startswith("/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "... absolute `https://` URLs using request host."
# Context: the host comes from the request, not from the bind address.
# ---------------------------------------------------------------------------
def test_absolute_url_uses_the_request_host_header(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": "true"})
    url = origin.add("/tls-host-header.csv", A)
    resp = gate.get("/convert", params={"source": url},
                    headers={"Host": "data.example.com"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["endpoint"].startswith("https://data.example.com/datasets/")


# ---------------------------------------------------------------------------
# Phrase: "same endpoints"
# Context: only the URL form changes -- the dataset id is unaffected by TLS.
# ---------------------------------------------------------------------------
def test_tls_changes_only_the_url_form_not_the_dataset_id(fresh_gate, origin):
    off = fresh_gate(port=free_port(), address="127.0.0.1",
                     env={"REQUIRE_TLS": "off"})
    on = fresh_gate(port=free_port(), address="127.0.0.1",
                    env={"REQUIRE_TLS": "on"})
    url = origin.add("/tls-same-id.csv", A)
    relative = off.convert(source=url).json()["endpoint"]
    absolute = on.convert(source=url).json()["endpoint"]
    assert urlparse(absolute).path == relative


# ---------------------------------------------------------------------------
# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs"
# Context: the returned path still resolves against the running service.
# ---------------------------------------------------------------------------
def test_absolute_endpoint_path_is_queryable(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": "1"})
    url = origin.add("/tls-queryable.csv", A)
    endpoint = gate.convert(source=url).json()["endpoint"]
    resp = gate.get(urlparse(endpoint).path)
    assert resp.status_code == 200
    assert resp.json()["columns"] == ["city", "pop"]


# ---------------------------------------------------------------------------
# Phrase: "`REQUIRE_TLS` | boolean" configured through the config file
# Context: REQUIRE_TLS is a setting like any other.
# ---------------------------------------------------------------------------
def test_require_tls_from_the_config_file(fresh_gate, origin, tmp_path):
    cfg = write_config(tmp_path, "# tls\nREQUIRE_TLS=yes\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    url = origin.add("/tls-cfg.csv", A)
    assert gate.convert(source=url).json()["endpoint"].startswith("https://")


# ---------------------------------------------------------------------------
# Phrase: "`REQUIRE_TLS=true`: same endpoints ..."
# Context: TLS affects the endpoint URL only; plain-HTTP requests still work.
# ---------------------------------------------------------------------------
def test_plain_http_requests_still_succeed_with_tls_required(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": "true"})
    url = origin.add("/tls-http-ok.csv", A)
    assert gate.convert(source=url).status_code == 200
    endpoint = gate.convert(source=url).json()["endpoint"]
    assert gate.get(urlparse(endpoint).path).status_code == 200


# ---------------------------------------------------------------------------
# Phrase: "`/convert` and `/upload` return relative endpoints" (error paths)
# Context: failures carry no endpoint at all, in either TLS mode.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tls", ["true", "false"])
def test_errors_carry_no_endpoint_in_either_mode(fresh_gate, tls):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"REQUIRE_TLS": tls})
    body = gate.get("/convert").json()
    assert body["ok"] is False
    assert "endpoint" not in body
