"""Spec section: Origin Allowlist.

    If configured, check every request before routing:
    1. Require `Referer`.
    2. Parse hostname.
    3. Accept only hostnames matching any allowed suffix case-insensitively
       with domain-boundary rules.
    4. Otherwise return `HTTP 403`.
    No allowlist means all requests pass.
"""

import pytest

SIMPLE = "name,age\nalice,30\nbob,41\n"


def ref(url):
    return {"Referer": url}


# ---------------------------------------------------------------------------
# "No allowlist means all requests pass."
# ---------------------------------------------------------------------------


# Phrase: "No allowlist means all requests pass."  (no Referer at all)
def test_no_allowlist_allows_a_request_without_referer(configure, convert):
    assert configure() is None
    assert convert("/allow-off.csv", SIMPLE).status_code == 200


# Phrase: "No allowlist means all requests pass."  (arbitrary Referer)
def test_no_allowlist_allows_any_referer(configure, client, origin):
    assert configure() is None
    origin.add("/allow-off2.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-off2.csv")},
                          headers=ref("http://anywhere.example/page"))
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "No allowlist means all requests pass." -- an empty ORIGIN_ALLOWLIST
# is the same as none at all (AMBIGUITIES T64).
def test_empty_allowlist_is_no_allowlist(configure, convert):
    assert configure(ORIGIN_ALLOWLIST="") is None
    assert convert("/allow-empty.csv", SIMPLE).status_code == 200


# ---------------------------------------------------------------------------
# 1. Require `Referer`.
# ---------------------------------------------------------------------------


# Phrase: "1. Require `Referer`." / table row "Missing `Referer` (allowlist
# active) | 403 | {"ok": false, "error": "<message>"}"
def test_missing_referer_is_403(configure, client, origin):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-none.csv")})
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"].strip()


# Phrase: "1. Require `Referer`." -- a header present but empty conveys no
# referrer, so it is a missing one (AMBIGUITIES T74).
def test_empty_referer_is_403(configure, client, origin):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-empty-ref.csv")},
                          headers=ref(""))
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


# Phrase: "1. Require `Referer`." -- the request is refused before it is
# served, so an oversized/invalid request never reaches its own validation
# (AMBIGUITIES T80).
def test_missing_referer_wins_over_other_faults(configure, client):
    assert configure(ORIGIN_ALLOWLIST="example.com", MAX_SOURCE_SIZE="1") is None
    assert client.get("/convert").status_code == 403          # missing `source`
    assert client.get("/convert", query_string={"source": "nonsense"}).status_code == 403


# ---------------------------------------------------------------------------
# 2. Parse hostname. / 3. suffix match with domain-boundary rules.
# ---------------------------------------------------------------------------


# Phrase: "3. Accept only hostnames matching any allowed suffix" -- the apex
# itself matches (AMBIGUITIES T72).
def test_apex_hostname_is_allowed(configure, client, origin):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    origin.add("/allow-apex.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-apex.csv")},
                          headers=ref("http://example.com/page.html"))
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "matching any allowed suffix ... with domain-boundary rules"
@pytest.mark.parametrize("host", ["example.com", "www.example.com",
                                  "a.b.example.com", "EXAMPLE.com"])
def test_hostnames_on_a_label_boundary_are_allowed(configure, client, origin, host):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    origin.add("/allow-sub.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-sub.csv")},
                          headers=ref("https://{}/x".format(host)))
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "with domain-boundary rules" -- a textual suffix that does not land
# on a label boundary is rejected.
@pytest.mark.parametrize("host", ["notexample.com", "badexample.com",
                                  "example.com.evil.net", "example.co",
                                  "com", "evil.net"])
def test_hostnames_off_the_label_boundary_are_403(configure, client, origin, host):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-bad.csv")},
                          headers=ref("https://{}/x".format(host)))
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


# Phrase: "case-insensitively" -- in both the header and the configured suffix.
@pytest.mark.parametrize("suffix,host", [
    ("example.com", "WWW.EXAMPLE.COM"),
    ("EXAMPLE.COM", "www.example.com"),
    ("Example.Com", "A.ExAmPlE.cOm"),
])
def test_matching_ignores_case_on_both_sides(configure, client, origin, suffix, host):
    assert configure(ORIGIN_ALLOWLIST=suffix) is None
    origin.add("/allow-case.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-case.csv")},
                          headers=ref("http://{}/p".format(host)))
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "matching any allowed suffix" -- any entry of the list may match.
@pytest.mark.parametrize("host", ["one.test", "sub.two.test"])
def test_any_entry_of_the_list_may_match(configure, client, origin, host):
    assert configure(ORIGIN_ALLOWLIST="one.test,two.test") is None
    origin.add("/allow-list.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-list.csv")},
                          headers=ref("http://{}/p".format(host)))
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "matching any allowed suffix" -- a host matching no entry is 403.
def test_host_matching_no_entry_is_403(configure, client, origin):
    assert configure(ORIGIN_ALLOWLIST="one.test,two.test") is None
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-list2.csv")},
                          headers=ref("http://three.test/p"))
    assert response.status_code == 403


# Phrase: "2. Parse hostname." -- the port, userinfo, path and query of the
# Referer are not part of the hostname.
@pytest.mark.parametrize("referer", [
    "http://www.example.com:8080/page?q=1#frag",
    "https://user:pw@www.example.com/page",
    "https://www.example.com",
])
def test_hostname_is_parsed_out_of_the_referer(configure, client, origin, referer):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    origin.add("/allow-parse.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-parse.csv")},
                          headers=ref(referer))
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "2. Parse hostname." / "4. Otherwise return `HTTP 403`." -- a Referer
# with no hostname to parse (AMBIGUITIES T74).
@pytest.mark.parametrize("referer", ["/relative/page", "about:blank",
                                     "not a url", "http://", "example.com/page"])
def test_referer_without_a_hostname_is_403(configure, client, origin, referer):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-nohost.csv")},
                          headers=ref(referer))
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


# Phrase: table row "Referer not allowed | 403 | {"ok": false, "error": "..."}"
def test_disallowed_referer_uses_the_standard_envelope(configure, client, origin):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-env.csv")},
                          headers=ref("http://evil.test/p"))
    assert response.status_code == 403
    assert response.mimetype == "application/json"
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"].strip()


# ---------------------------------------------------------------------------
# "check every request before routing"
# ---------------------------------------------------------------------------


# Phrase: "check every request before routing" -- every endpoint, not just the
# ingest ones (AMBIGUITIES T73).
def test_every_endpoint_is_gated(configure, client, origin, upload):
    assert configure() is None
    endpoint = upload(SIMPLE).get_json()["endpoint"]

    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    for path in ("/convert", "/upload", endpoint, endpoint + "/export"):
        response = client.get(path)
        assert response.status_code == 403, (path, response.status_code)
        assert response.get_json()["ok"] is False


# Phrase: "check every request before routing" -- an unknown path is refused
# before it can be found to be unknown, so 403 rather than 404 (T73).
def test_unknown_routes_are_gated_before_routing(configure, client):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    response = client.get("/no/such/route")
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


# Phrase: "check every request before routing" -- and an allowed Referer lets
# the request through to its normal (404) routing outcome.
def test_allowed_referer_reaches_normal_routing(configure, client):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    response = client.get("/no/such/route", headers=ref("http://example.com/"))
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "check every request before routing" -- POST /upload is gated too.
def test_upload_is_gated(configure, client, upload):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    assert upload(SIMPLE).status_code == 403
    assert upload(SIMPLE, headers=ref("http://example.com/form")).status_code == 200


# Phrase: "check every request before routing" -- a whole-list configuration
# coming from the DATAGATE_CONFIG file behaves identically.
def test_allowlist_from_the_config_file(configure, config_file, client, origin):
    path = config_file("ORIGIN_ALLOWLIST=example.com, other.test\n")
    assert configure(DATAGATE_CONFIG=path) is None
    origin.add("/allow-file.csv", SIMPLE)
    source = origin.url("/allow-file.csv")
    assert client.get("/convert", query_string={"source": source},
                      headers=ref("http://x.other.test/")).status_code == 200
    assert client.get("/convert", query_string={"source": source},
                      headers=ref("http://nope.test/")).status_code == 403


# Phrase: "3. Accept only hostnames matching any allowed suffix" -- a leading
# dot on an entry is normalized away (AMBIGUITIES T72).
@pytest.mark.parametrize("host", ["example.com", "www.example.com"])
def test_leading_dot_entry_matches_apex_and_subdomains(configure, client, origin, host):
    assert configure(ORIGIN_ALLOWLIST=".example.com") is None
    origin.add("/allow-dot.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-dot.csv")},
                          headers=ref("http://{}/p".format(host)))
    assert response.status_code == 200, response.get_data(as_text=True)


# Phrase: "check every request before routing" -- an allowed request keeps the
# CORS headers the earlier spec section requires.
def test_allowed_request_still_carries_cors_headers(configure, client, origin):
    assert configure(ORIGIN_ALLOWLIST="example.com") is None
    origin.add("/allow-cors.csv", SIMPLE)
    response = client.get("/convert",
                          query_string={"source": origin.url("/allow-cors.csv")},
                          headers=ref("http://example.com/"))
    assert response.headers.get("Access-Control-Allow-Origin") == "*"
