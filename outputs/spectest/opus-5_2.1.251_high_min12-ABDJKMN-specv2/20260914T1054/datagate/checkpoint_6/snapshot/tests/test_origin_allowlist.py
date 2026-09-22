"""Spec section: Origin Allowlist.

The allowlist is a request gate, so every test here drives a plain request and looks at
the status code; the four numbered steps of the spec are covered in order.
"""
import io
import urllib.parse

import pytest

from conftest import assert_error_envelope

CSV = "name,qty\nwidget,3\n"


def get(client, path, referer=None, **kwargs):
    headers = {} if referer is None else {"Referer": referer}
    return client.get(path, headers=headers, **kwargs)


def convert(client, url, referer=None):
    query = "source=" + urllib.parse.quote(url, safe="")
    return get(client, "/convert", referer, query_string=query)


def upload(client, referer=None, body=CSV):
    headers = {} if referer is None else {"Referer": referer}
    return client.post("/upload",
                       data={"file": (io.BytesIO(body.encode("utf-8")), "d.csv")},
                       content_type="multipart/form-data", headers=headers)


# =============================================================================
# Phrase: "No allowlist means all requests pass."
# Context: the default - ORIGIN_ALLOWLIST unset - changes nothing at all.
# =============================================================================

def test_without_an_allowlist_a_request_with_no_referer_passes(make_app, origin):
    client = make_app().test_client()
    assert convert(client, origin.add(CSV)).status_code == 200


def test_without_an_allowlist_any_referer_passes(make_app, origin):
    client = make_app().test_client()
    assert convert(client, origin.add(CSV), "https://evil.example/p").status_code == 200


def test_without_an_allowlist_a_nonsense_referer_passes(make_app, origin):
    client = make_app().test_client()
    assert convert(client, origin.add(CSV), "not a url").status_code == 200


def test_empty_allowlist_means_no_allowlist(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="").test_client()
    assert convert(client, origin.add(CSV)).status_code == 200


def test_without_an_allowlist_unknown_paths_still_404(make_app):
    client = make_app().test_client()
    assert get(client, "/nope").status_code == 404


# =============================================================================
# Phrase: "1. Require `Referer`."
# Context: with an allowlist configured, a request with no Referer is refused.
# =============================================================================

def test_missing_referer_is_403(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert_error_envelope(convert(client, origin.add(CSV)), 403)


def test_missing_referer_on_a_dataset_read_is_403(make_app):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert_error_envelope(get(client, "/datasets/abc"), 403)


def test_empty_referer_header_counts_as_missing(make_app, origin):
    """`Referer: ` carries no origin (AMBIGUITIES T73)."""
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert_error_envelope(convert(client, origin.add(CSV), ""), 403)


def test_whitespace_only_referer_counts_as_missing(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert_error_envelope(convert(client, origin.add(CSV), "   "), 403)


def test_missing_referer_never_reaches_the_source(make_app, origin):
    """The gate runs before routing, so nothing is downloaded."""
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    url = origin.add(CSV)
    before = origin.hits(url)
    assert convert(client, url).status_code == 403
    assert origin.hits(url) == before


# =============================================================================
# Phrase: "2. Parse hostname."
# Context: only the host part of the Referer matters - not scheme, port, path,
#          userinfo or query.
# =============================================================================

@pytest.mark.parametrize("referer", [
    "https://example.com/",
    "http://example.com/some/path?q=1#frag",
    "https://example.com:8443/page",
    "https://user:pw@example.com/page",
    "https://example.com",
])
def test_hostname_is_extracted_from_the_referer(make_app, origin, referer):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert convert(client, origin.add(CSV), referer).status_code == 200


@pytest.mark.parametrize("referer", [
    "example.com/page",       # no scheme: urlparse finds no host
    "about:blank",
    "not a url",
    "https:///onlypath",
    "/relative/path",
])
def test_referer_with_no_parseable_hostname_is_403(make_app, origin, referer):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert_error_envelope(convert(client, origin.add(CSV), referer), 403)


def test_a_port_does_not_make_the_host_a_different_host(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert convert(client, origin.add(CSV),
                   "https://app.example.com:9999/x").status_code == 200


# =============================================================================
# Phrase: "3. Accept only hostnames matching any allowed suffix"
# Context: the exact host and any sub-domain of it are accepted.
# =============================================================================

@pytest.mark.parametrize("host", [
    "example.com",
    "www.example.com",
    "a.b.c.example.com",
])
def test_exact_host_and_subdomains_match(make_app, origin, host):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert convert(client, origin.add(CSV),
                   "https://%s/page" % host).status_code == 200


def test_any_of_several_suffixes_may_match(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="a.test,example.com,b.test").test_client()
    for host in ("a.test", "deep.example.com", "b.test"):
        assert convert(client, origin.add(CSV),
                       "https://%s/p" % host).status_code == 200


def test_a_host_matching_no_suffix_is_403(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="a.test,b.test").test_client()
    assert_error_envelope(convert(client, origin.add(CSV), "https://c.test/p"), 403)


def test_a_suffix_written_with_a_leading_dot_still_matches(make_app, origin):
    """`.example.com` is the same allowlist entry as `example.com` (T71)."""
    client = make_app(ORIGIN_ALLOWLIST=".example.com").test_client()
    assert convert(client, origin.add(CSV),
                   "https://www.example.com/p").status_code == 200
    assert convert(client, origin.add(CSV), "https://example.com/p").status_code == 200


def test_an_ip_address_referer_matches_only_an_identical_entry(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="127.0.0.1").test_client()
    assert convert(client, origin.add(CSV), "http://127.0.0.1:9/p").status_code == 200
    assert convert(client, origin.add(CSV), "http://10.0.0.1/p").status_code == 403


# =============================================================================
# Phrase: "... case-insensitively ..."
# Context: host names and configured suffixes compare without regard to case.
# =============================================================================

@pytest.mark.parametrize("host", ["EXAMPLE.COM", "Example.Com", "WWW.Example.COM"])
def test_referer_host_case_is_ignored(make_app, origin, host):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert convert(client, origin.add(CSV),
                   "https://%s/page" % host).status_code == 200


@pytest.mark.parametrize("entry", ["EXAMPLE.COM", "Example.com"])
def test_configured_suffix_case_is_ignored(make_app, origin, entry):
    client = make_app(ORIGIN_ALLOWLIST=entry).test_client()
    assert convert(client, origin.add(CSV),
                   "https://www.example.com/p").status_code == 200


# =============================================================================
# Phrase: "... with domain-boundary rules."
# Context: a textual suffix match that does not land on a label boundary is
#          not a match (AMBIGUITIES T71).
# =============================================================================

@pytest.mark.parametrize("host", [
    "notexample.com",        # bare endswith would match
    "myexample.com",
    "example.com.evil.net",  # suffix in the middle
    "example.co",            # shorter
    "example.common",
    "xexample.com",
])
def test_boundary_violations_are_403(make_app, origin, host):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert_error_envelope(convert(client, origin.add(CSV),
                                  "https://%s/p" % host), 403)


def test_a_dash_before_the_suffix_is_not_a_boundary(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert convert(client, origin.add(CSV),
                   "https://evil-example.com/p").status_code == 403


def test_a_deeper_suffix_does_not_admit_its_parent(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="app.example.com").test_client()
    assert convert(client, origin.add(CSV), "https://example.com/p").status_code == 403
    assert convert(client, origin.add(CSV),
                   "https://x.app.example.com/p").status_code == 200


# =============================================================================
# Phrase: "If configured, check every request before routing"
# Context: every path and every method is gated, and the gate wins over the
#          error the route itself would have produced (AMBIGUITIES T72).
# =============================================================================

@pytest.mark.parametrize("path", [
    "/convert", "/upload", "/datasets/abc", "/datasets/abc/export", "/", "/nope",
])
def test_every_path_is_gated(make_app, path):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert get(client, path).status_code == 403


def test_an_unknown_path_is_403_not_404(make_app):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert_error_envelope(get(client, "/no/such/route"), 403)


def test_options_preflight_is_gated_too(make_app):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert client.options("/convert").status_code == 403


def test_options_preflight_with_an_allowed_referer_still_works(make_app):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    response = client.options("/convert", headers={"Referer": "https://example.com/"})
    assert response.status_code == 204


def test_the_gate_precedes_parameter_validation(make_app):
    """A request that is *also* a 400 answers 403, because the gate runs first."""
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert get(client, "/convert").status_code == 403           # missing `source`
    assert get(client, "/convert", "https://example.com/").status_code == 400


def test_the_gate_precedes_the_size_limit(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="example.com",
                      MAX_SOURCE_SIZE="1").test_client()
    assert convert(client, origin.add(CSV)).status_code == 403
    assert convert(client, origin.add(CSV), "https://example.com/").status_code == 400


def test_upload_is_gated(make_app):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert_error_envelope(upload(client), 403)
    assert upload(client, "https://example.com/p").status_code == 200


def test_a_wrong_method_is_403_not_405(make_app):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    assert client.post("/datasets/abc").status_code == 403


# =============================================================================
# Phrase (error table): "Missing `Referer` (allowlist active) | 403" and
#                       "Referer not allowed | 403"
# Context: both are the standard envelope with a non-empty message.
# =============================================================================

def test_missing_referer_envelope(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    payload = assert_error_envelope(convert(client, origin.add(CSV)), 403)
    assert payload["ok"] is False


def test_disallowed_referer_envelope(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    payload = assert_error_envelope(
        convert(client, origin.add(CSV), "https://evil.test/p"), 403)
    assert payload["ok"] is False


def test_forbidden_responses_are_json(make_app):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    response = get(client, "/datasets/abc")
    assert response.headers["Content-Type"].startswith("application/json")


def test_forbidden_responses_carry_cors_headers(make_app):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    response = get(client, "/datasets/abc")
    assert response.headers["Access-Control-Allow-Origin"] == "*"


# =============================================================================
# Phrase: "If configured, check every request" - an allowed request behaves
#          exactly as it would with no allowlist at all.
# Context: the gate must not otherwise alter the response.
# =============================================================================

def test_an_allowed_request_gets_the_ordinary_response(make_app, origin):
    client = make_app(ORIGIN_ALLOWLIST="example.com").test_client()
    url = origin.add(CSV)
    response = convert(client, url, "https://example.com/page")
    assert response.status_code == 200
    endpoint = response.get_json()["endpoint"]
    payload = get(client, endpoint, "https://example.com/page").get_json()
    assert payload["columns"] == ["name", "qty"]
    assert payload["rows"] == [["widget", 3]]
