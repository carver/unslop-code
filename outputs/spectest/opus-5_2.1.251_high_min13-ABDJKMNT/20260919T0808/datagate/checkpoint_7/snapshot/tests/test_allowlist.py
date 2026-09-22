"""Spec section: Origin Allowlist."""

import io

import pytest

from datagate_core.access import host_allowed

SIMPLE_CSV = "name,age\nada,36\n"


@pytest.fixture
def gated(configured_client):
    """A client started with `ORIGIN_ALLOWLIST` set to a comma-joined list."""

    def _gated(*suffixes):
        return configured_client(ORIGIN_ALLOWLIST=",".join(suffixes) if suffixes else None)

    return _gated


def get(client, path, referer=None):
    headers = {"Referer": referer} if referer is not None else {}
    return client.get(path, headers=headers)


# Phrase: "1. Require `Referer`." - a request without the header is refused.
def test_a_missing_referer_is_refused(gated):
    assert get(gated("example.test"), "/datasets/anything").status_code == 403


# Phrase: "Missing `Referer` (allowlist active) | 403 |
# `{"ok": false, "error": "<message>"}`".
def test_the_missing_referer_error_uses_the_standard_envelope(gated):
    payload = get(gated("example.test"), "/datasets/anything").get_json()

    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    assert set(payload) == {"ok", "error"}


# Phrase: "3. Accept only hostnames matching any allowed suffix" - an exact
# hostname match passes.
def test_an_exact_hostname_is_accepted(gated, origin):
    url = origin.serve("/allow-exact.csv", SIMPLE_CSV)
    response = get(gated("example.test"), f"/convert?source={url}", "http://example.test/page")

    assert response.status_code == 200


# Phrase: "2. Parse hostname." - the hostname comes out of the URL, so a path,
# a port and a query on the `Referer` are not part of the comparison.
@pytest.mark.parametrize(
    "referer",
    [
        "http://example.test/",
        "https://example.test/deep/path?q=1#fragment",
        "http://example.test:8080/page",
        "http://user:pw@example.test/page",
    ],
)
def test_the_hostname_is_parsed_out_of_the_referer(gated, referer):
    assert get(gated("example.test"), "/datasets/missing", referer).status_code == 404


# Phrase: "4. Otherwise return `HTTP 403`." - a hostname outside the list.
def test_a_hostname_outside_the_list_is_refused(gated):
    assert get(gated("example.test"), "/datasets/missing", "http://other.test/").status_code == 403


# Phrase: "Referer not allowed | 403 | `{"ok": false, "error": "<message>"}`".
def test_the_not_allowed_error_uses_the_standard_envelope(gated):
    payload = get(gated("example.test"), "/datasets/missing", "http://other.test/").get_json()

    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    assert set(payload) == {"ok", "error"}


# Phrase: "matching any allowed suffix" - any one entry of the list is enough.
@pytest.mark.parametrize("host", ["a.test", "b.test", "www.b.test"])
def test_any_entry_of_the_list_may_match(gated, host):
    assert get(gated("a.test", "b.test"), "/datasets/missing", f"http://{host}/").status_code == 404


# Phrase: "case-insensitively" - in the hostname and in the configured suffix.
@pytest.mark.parametrize(
    "suffix,host", [("example.test", "EXAMPLE.TEST"), ("EXAMPLE.TEST", "example.test")]
)
def test_matching_ignores_case(gated, suffix, host):
    assert get(gated(suffix), "/datasets/missing", f"http://{host}/").status_code == 404


# Phrase: "with domain-boundary rules" - a subdomain matches its parent suffix.
@pytest.mark.parametrize("host", ["example.test", "www.example.test", "a.b.example.test"])
def test_subdomains_match_their_suffix(host):
    assert host_allowed(host, ("example.test",))


# Phrase: "with domain-boundary rules" - a hostname that merely ends with the
# suffix's characters, without a label boundary, does not match (T65).
@pytest.mark.parametrize("host", ["notexample.test", "evil-example.test", "xexample.test"])
def test_a_suffix_match_without_a_label_boundary_is_refused(host):
    assert not host_allowed(host, ("example.test",))


# Phrase: "with domain-boundary rules" - and the refusal is a 403 over HTTP.
def test_a_boundary_straddling_hostname_is_refused_over_http(gated):
    response = get(gated("example.test"), "/datasets/missing", "http://notexample.test/")

    assert response.status_code == 403


# Phrase: "list of domain suffixes" - a suffix written with a leading dot, and a
# hostname written with the root dot, mean the same domain (T65).
@pytest.mark.parametrize(
    "suffix,host",
    [(".example.test", "www.example.test"), ("example.test", "www.example.test.")],
)
def test_dotted_spellings_match_the_same_domain(suffix, host):
    assert host_allowed(host, (suffix,))


# Phrase: "2. Parse hostname." / "4. Otherwise ..." - a `Referer` carrying no
# hostname cannot match, so it is 403 (T67).
@pytest.mark.parametrize("referer", ["", "about:blank", "/relative/page", "not a url"])
def test_a_referer_without_a_hostname_is_refused(gated, referer):
    assert get(gated("example.test"), "/datasets/missing", referer).status_code == 403


# Phrase: "check every request before routing" - the gate runs ahead of the
# router, so an unknown path is refused rather than 404ed (T66).
def test_the_check_runs_before_routing(gated):
    assert get(gated("example.test"), "/no/such/route").status_code == 403


# Phrase: "check every request" - every route is behind the gate, not just the
# ingestion routes (T66).
@pytest.mark.parametrize(
    "path", ["/convert?source=http://x.test/a.csv", "/datasets/abc", "/datasets/abc/export"]
)
def test_every_route_is_behind_the_gate(gated, path):
    assert get(gated("example.test"), path).status_code == 403


# Phrase: "check every request" - `/upload` too, and before its media type is judged.
def test_upload_is_behind_the_gate(gated):
    client = gated("example.test")
    response = client.post(
        "/upload",
        data={"file": (io.BytesIO(SIMPLE_CSV.encode()), "data.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 403


# Phrase: "No allowlist means all requests pass." - without the setting, a
# request with no `Referer` at all reaches its route.
def test_no_allowlist_lets_every_request_through(gated, origin):
    url = origin.serve("/allow-none.csv", SIMPLE_CSV)
    client = gated()

    assert client.get(f"/convert?source={url}").status_code == 200
    assert client.get("/datasets/missing").status_code == 404


# Phrase: "No allowlist means all requests pass." - including one whose `Referer`
# names a host no deployment would allow.
def test_no_allowlist_ignores_the_referer(gated):
    assert get(gated(), "/datasets/missing", "http://anywhere.test/").status_code == 404


# Phrase: "If configured, check every request ..." - an allowed request is served
# normally, envelope and all.
def test_an_allowed_request_is_served_normally(gated, origin):
    url = origin.serve("/allow-served.csv", SIMPLE_CSV)
    client = gated("example.test")
    converted = get(client, f"/convert?source={url}", "https://app.example.test/")

    assert converted.status_code == 200
    endpoint = converted.get_json()["endpoint"]
    assert get(client, endpoint, "https://app.example.test/").get_json()["columns"] == [
        "name",
        "age",
    ]


# Phrase: "check every request before routing" vs "Enforced for `/convert` and
# `/upload`" - the gate runs first, so a disallowed oversized upload is 403 (T72).
def test_the_allowlist_is_checked_before_the_size_limit(configured_client):
    client = configured_client(ORIGIN_ALLOWLIST="example.test", MAX_SOURCE_SIZE=1)
    response = client.post(
        "/upload",
        data={"file": (io.BytesIO(SIMPLE_CSV.encode()), "data.csv")},
        content_type="multipart/form-data",
        headers={"Referer": "http://other.test/"},
    )

    assert response.status_code == 403
