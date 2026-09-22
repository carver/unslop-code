"""Spec section: Origin Allowlist."""
import pytest

from conftest import (
    assert_error_envelope,
    convert_ok,
    free_port,
    upload,
    write_config,
)

A = "city,pop\nOslo,700000\n"


def ref(host, path="/page.html", scheme="http"):
    return {"Referer": f"{scheme}://{host}{path}"}


# ---------------------------------------------------------------------------
# Phrase: "No allowlist means all requests pass."
# Context: ORIGIN_ALLOWLIST unset -- a Referer-less request is routed normally.
# ---------------------------------------------------------------------------
def test_no_allowlist_lets_every_request_through(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1")
    url = origin.add("/acl-none.csv", A)
    endpoint = convert_ok(gate, url)          # no Referer at all
    assert gate.get(endpoint).status_code == 200
    assert gate.get(endpoint, headers=ref("anywhere.example")).status_code == 200


# ---------------------------------------------------------------------------
# Phrase: "If configured, check every request before routing: 1. Require `Referer`."
# Context: allowlist active, request carries no Referer header.
# ---------------------------------------------------------------------------
def test_missing_referer_is_403(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    url = origin.add("/acl-missing-ref.csv", A)
    assert_error_envelope(gate.convert(source=url), 403)


# ---------------------------------------------------------------------------
# Phrase: "Missing `Referer` (allowlist active) | 403 |
#          `{"ok": false, "error": "<message>"}`"
# Context: the error table pins the body shape.
# ---------------------------------------------------------------------------
def test_missing_referer_uses_the_standard_envelope(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    body = assert_error_envelope(gate.get("/datasets/anything"), 403)
    assert set(body) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: "1. Require `Referer`."
# Context: a present but empty Referer supplies no origin at all.
# ---------------------------------------------------------------------------
def test_empty_referer_is_403(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert_error_envelope(
        gate.get("/datasets/anything", headers={"Referer": ""}), 403
    )


# ---------------------------------------------------------------------------
# Phrase: "2. Parse hostname."
# Context: a Referer that has no parseable hostname cannot be allowed.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value", ["not a url", "/relative/path", "about:blank", "http://", "example.com"]
)
def test_referer_without_a_hostname_is_403(fresh_gate, value):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert_error_envelope(
        gate.get("/datasets/anything", headers={"Referer": value}), 403
    )


# ---------------------------------------------------------------------------
# Phrase: "3. Accept only hostnames matching any allowed suffix ..."
# Context: the hostname is exactly the configured suffix.
# ---------------------------------------------------------------------------
def test_exact_hostname_match_is_accepted(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    url = origin.add("/acl-exact.csv", A)
    resp = gate.get("/convert", params={"source": url}, headers=ref("example.com"))
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Phrase: "... matching any allowed suffix ... with domain-boundary rules."
# Context: a subdomain of an allowed suffix is inside the boundary.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["www.example.com", "a.b.example.com"])
def test_subdomain_of_an_allowed_suffix_is_accepted(fresh_gate, host):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert gate.get("/datasets/nope", headers=ref(host)).status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "... with domain-boundary rules."
# Context: a bare suffix match that does not land on a label boundary.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["notexample.com", "badexample.com", "xexample.com"])
def test_suffix_without_a_label_boundary_is_rejected(fresh_gate, host):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert_error_envelope(gate.get("/datasets/nope", headers=ref(host)), 403)


# ---------------------------------------------------------------------------
# Phrase: "... matching any allowed suffix ..."
# Context: the allowed domain appearing as a prefix, not a suffix.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["example.com.evil.test", "example.common"])
def test_allowed_domain_as_a_prefix_is_rejected(fresh_gate, host):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert_error_envelope(gate.get("/datasets/nope", headers=ref(host)), 403)


# ---------------------------------------------------------------------------
# Phrase: "... matching any allowed suffix case-insensitively ..."
# Context: mixed case in the Referer host and in the configured suffix.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["EXAMPLE.COM", "WWW.Example.Com"])
def test_hostname_matching_is_case_insensitive(fresh_gate, host):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "ExAmPlE.CoM"})
    assert gate.get("/datasets/nope", headers=ref(host)).status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "matching any allowed suffix" (plural list)
# Context: several suffixes configured; each one independently admits a host.
# ---------------------------------------------------------------------------
def test_any_of_several_suffixes_admits_a_request(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "one.test,two.test,three.test"})
    for host in ("one.test", "sub.two.test", "three.test"):
        assert gate.get("/datasets/nope", headers=ref(host)).status_code == 404
    assert_error_envelope(gate.get("/datasets/nope", headers=ref("four.test")), 403)


# ---------------------------------------------------------------------------
# Phrase: "2. Parse hostname."
# Context: a port and userinfo are not part of the hostname.
# ---------------------------------------------------------------------------
def test_port_and_userinfo_are_not_part_of_the_hostname(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert gate.get("/datasets/nope",
                    headers={"Referer": "http://example.com:8080/p"}).status_code == 404
    assert gate.get("/datasets/nope",
                    headers={"Referer": "http://user:pw@www.example.com/p"}).status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "3. Accept only hostnames matching any allowed suffix"
# Context: an https Referer is judged on its hostname, not its scheme.
# ---------------------------------------------------------------------------
def test_scheme_does_not_affect_allowlist_matching(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert gate.get("/datasets/nope",
                    headers=ref("example.com", scheme="https")).status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "4. Otherwise return `HTTP 403`."
# Context: "Referer not allowed" body shape from the error table.
# ---------------------------------------------------------------------------
def test_disallowed_referer_uses_the_standard_envelope(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    body = assert_error_envelope(gate.get("/datasets/nope", headers=ref("evil.test")), 403)
    assert set(body) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: "check every request before routing"
# Context: the check runs ahead of routing, so an unknown path is 403, not 404.
# ---------------------------------------------------------------------------
def test_check_precedes_routing_for_unknown_paths(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert gate.get("/no-such-route").status_code == 403
    assert gate.get("/datasets/nope").status_code == 403


# ---------------------------------------------------------------------------
# Phrase: "check every request before routing"
# Context: the check precedes /convert's own parameter validation.
# ---------------------------------------------------------------------------
def test_check_precedes_request_validation(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert gate.get("/convert").status_code == 403           # missing source
    assert gate.get("/convert", params={"source": "nope"}).status_code == 403


# ---------------------------------------------------------------------------
# Phrase: "check every request"
# Context: POST /upload is a request like any other.
# ---------------------------------------------------------------------------
def test_upload_is_subject_to_the_allowlist(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert_error_envelope(upload(gate, A), 403)
    resp = gate.request(
        "POST", "/upload",
        files={"file": ("t.csv", A.encode(), "text/csv")},
        headers=ref("www.example.com"),
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Phrase: "check every request"
# Context: dataset queries and exports are checked too.
# ---------------------------------------------------------------------------
def test_queries_and_exports_are_subject_to_the_allowlist(fresh_gate, origin):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    url = origin.add("/acl-query.csv", A)
    allowed = ref("example.com")
    endpoint = gate.get("/convert", params={"source": url},
                        headers=allowed).json()["endpoint"]
    assert gate.get(endpoint, headers=allowed).status_code == 200
    assert gate.get(endpoint + "/export", headers=allowed).status_code == 200
    assert gate.get(endpoint).status_code == 403
    assert gate.get(endpoint + "/export").status_code == 403


# ---------------------------------------------------------------------------
# Phrase: "ORIGIN_ALLOWLIST | list of domain suffixes" from the config file
# Context: the allowlist is configurable through DATAGATE_CONFIG.
# ---------------------------------------------------------------------------
def test_allowlist_from_the_config_file(fresh_gate, tmp_path):
    cfg = write_config(tmp_path, "ORIGIN_ALLOWLIST=example.com,internal.test\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg})
    assert gate.get("/datasets/nope", headers=ref("internal.test")).status_code == 404
    assert gate.get("/datasets/nope", headers=ref("other.test")).status_code == 403


# ---------------------------------------------------------------------------
# Phrase: "3. Direct environment variables" applied to ORIGIN_ALLOWLIST
# Context: the environment replaces (not extends) the file's list.
# ---------------------------------------------------------------------------
def test_allowlist_environment_overrides_config_file(fresh_gate, tmp_path):
    cfg = write_config(tmp_path, "ORIGIN_ALLOWLIST=file.test\n")
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"DATAGATE_CONFIG": cfg, "ORIGIN_ALLOWLIST": "env.test"})
    assert gate.get("/datasets/nope", headers=ref("env.test")).status_code == 404
    assert gate.get("/datasets/nope", headers=ref("file.test")).status_code == 403


# ---------------------------------------------------------------------------
# Phrase: "matching any allowed suffix ... with domain-boundary rules."
# Context: a suffix written with a leading dot still names the same domain.
# ---------------------------------------------------------------------------
def test_leading_dot_suffix_matches_the_domain_and_its_subdomains(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": ".example.com"})
    assert gate.get("/datasets/nope", headers=ref("www.example.com")).status_code == 404
    assert gate.get("/datasets/nope", headers=ref("example.com")).status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "2. Parse hostname."
# Context: a trailing-dot (fully qualified) hostname is the same host.
# ---------------------------------------------------------------------------
def test_trailing_dot_hostname_is_normalised(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "example.com"})
    assert gate.get("/datasets/nope",
                    headers={"Referer": "http://www.example.com./p"}).status_code == 404


# ---------------------------------------------------------------------------
# Phrase: "Accept only hostnames matching any allowed suffix"
# Context: an IP-literal allowlist entry matches that literal exactly.
# ---------------------------------------------------------------------------
def test_ip_literal_suffix_matches_itself(fresh_gate):
    gate = fresh_gate(port=free_port(), address="127.0.0.1",
                      env={"ORIGIN_ALLOWLIST": "127.0.0.1"})
    assert gate.get("/datasets/nope",
                    headers={"Referer": "http://127.0.0.1:9/p"}).status_code == 404
    assert_error_envelope(
        gate.get("/datasets/nope", headers={"Referer": "http://127.0.0.2/p"}), 403
    )
