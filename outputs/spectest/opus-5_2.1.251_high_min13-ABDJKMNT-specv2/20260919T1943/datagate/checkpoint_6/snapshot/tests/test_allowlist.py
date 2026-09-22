"""Spec section: Origin Allowlist."""

import pytest
from conftest import SIMPLE_CSV, SOURCE_URL

ALLOWED = "example.com"


@pytest.fixture
def guarded(configured):
    """A client whose app was started with `ORIGIN_ALLOWLIST=example.com`."""
    return configured(ORIGIN_ALLOWLIST=ALLOWED)


def get(client, path="/convert", referer=None, **params):
    headers = {} if referer is None else {"Referer": referer}
    return client.get(path, query_string=params, headers=headers)


# Phrase: "No allowlist means all requests pass." (context: no Referer at all)
def test_without_an_allowlist_a_refererless_request_passes(client, serve):
    serve(SIMPLE_CSV)

    assert get(client, source=SOURCE_URL).status_code == 200


# Phrase: "No allowlist means all requests pass." (context: a Referer nobody would allow)
def test_without_an_allowlist_any_referer_passes(client, serve):
    serve(SIMPLE_CSV)

    assert get(client, referer="https://evil.test/page", source=SOURCE_URL).status_code == 200


# Phrase: "1. Require `Referer`."
def test_missing_referer_is_403(guarded):
    assert get(guarded, source=SOURCE_URL).status_code == 403


# Phrase: "1. Require `Referer`." (context: an empty header value supplies no origin)
def test_empty_referer_is_403(guarded):
    assert get(guarded, referer="", source=SOURCE_URL).status_code == 403


# Phrase: "2. Parse hostname." (context: a Referer with no hostname to parse)
@pytest.mark.parametrize("referer", ["garbage", "/relative/page", "https://", "about:blank"])
def test_referer_without_a_hostname_is_403(guarded, referer):
    assert get(guarded, referer=referer, source=SOURCE_URL).status_code == 403


# Phrase: "3. Accept only hostnames matching any allowed suffix"
def test_exact_hostname_match_is_accepted(guarded, serve):
    serve(SIMPLE_CSV)

    assert get(guarded, referer="https://example.com/page", source=SOURCE_URL).status_code == 200


# Phrase: "... with domain-boundary rules." (context: a subdomain sits on a label boundary)
def test_subdomain_of_an_allowed_suffix_is_accepted(guarded, serve):
    serve(SIMPLE_CSV)

    assert get(guarded, referer="https://app.eu.example.com/page", source=SOURCE_URL).status_code == 200


# Phrase: "... case-insensitively ..." (context: the Referer is shouted)
def test_hostname_case_is_ignored(guarded, serve):
    serve(SIMPLE_CSV)

    assert get(guarded, referer="https://APP.EXAMPLE.COM/page", source=SOURCE_URL).status_code == 200


# Phrase: "... case-insensitively ..." (context: the configured suffix is shouted)
def test_configured_suffix_case_is_ignored(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(ORIGIN_ALLOWLIST="EXAMPLE.COM")

    assert get(client, referer="https://example.com/page", source=SOURCE_URL).status_code == 200


# Phrase: "... with domain-boundary rules." (context: a suffix that is not a whole-label match)
@pytest.mark.parametrize("host", ["notexample.com", "badexample.com", "example.com.evil.net", "evil.net"])
def test_hostnames_off_the_label_boundary_are_403(guarded, host):
    assert get(guarded, referer=f"https://{host}/page", source=SOURCE_URL).status_code == 403


# Phrase: "4. Otherwise return `HTTP 403`."
def test_disallowed_referer_uses_the_standard_envelope(guarded):
    body = get(guarded, referer="https://evil.test/page", source=SOURCE_URL).get_json()

    assert body["ok"] is False
    assert isinstance(body["error"], str) and body["error"].strip()
    assert set(body) == {"ok", "error"}


# Phrase: "1. Require `Referer`." (context: the missing-Referer failure is also the standard envelope)
def test_missing_referer_uses_the_standard_envelope(guarded):
    body = get(guarded, source=SOURCE_URL).get_json()

    assert body["ok"] is False and set(body) == {"ok", "error"}


# Phrase: "matching any allowed suffix" (context: a list, so any entry may match)
def test_any_configured_suffix_may_match(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(ORIGIN_ALLOWLIST="a.test,b.test")

    assert get(client, referer="https://b.test/page", source=SOURCE_URL).status_code == 200
    assert get(client, referer="https://c.test/page", source=SOURCE_URL).status_code == 403


# Phrase: "2. Parse hostname." (context: userinfo and port are not part of the hostname)
def test_port_and_userinfo_are_not_part_of_the_hostname(guarded, serve):
    serve(SIMPLE_CSV)

    assert get(guarded, referer="https://user@example.com:8443/page", source=SOURCE_URL).status_code == 200


# Phrase: "check every request before routing" (context: an unknown path is refused, not 404ed)
def test_unknown_routes_are_refused_before_routing(guarded):
    assert get(guarded, path="/definitely/not/a/route").status_code == 403


# Phrase: "check every request before routing" (context: dataset reads are requests too)
def test_dataset_and_export_routes_are_guarded(client, serve, guarded):
    serve(SIMPLE_CSV)
    endpoint = client.get("/convert", query_string={"source": SOURCE_URL}).get_json()["endpoint"]

    assert get(guarded, path=endpoint).status_code == 403
    assert get(guarded, path=endpoint + "/export").status_code == 403
    assert get(guarded, path=endpoint, referer="https://example.com/p").status_code == 200


# Phrase: "check every request before routing" (context: uploads are guarded too)
def test_upload_is_guarded(guarded):
    response = guarded.post("/upload", data={}, content_type="multipart/form-data")

    assert response.status_code == 403


# Phrase: "check every request before routing" (context: nothing is fetched for a refused request)
def test_refused_request_never_downloads(guarded, serve, remote):
    serve(SIMPLE_CSV)

    get(guarded, referer="https://evil.test/page", source=SOURCE_URL)

    assert len(remote.calls) == 0


# Phrase: "matching any allowed suffix ... with domain-boundary rules" (context: T62 -- a leading dot)
def test_leading_dot_suffix_matches_the_domain_and_its_subdomains(configured, serve):
    serve(SIMPLE_CSV)
    client = configured(ORIGIN_ALLOWLIST=".example.com")

    assert get(client, referer="https://example.com/p", source=SOURCE_URL).status_code == 200
    assert get(client, referer="https://app.example.com/p", source=SOURCE_URL).status_code == 200


# Phrase: "3. Accept only hostnames ..." (context: T62 -- a fully qualified trailing dot)
def test_trailing_dot_hostname_still_matches(guarded, serve):
    serve(SIMPLE_CSV)

    assert get(guarded, referer="https://example.com./p", source=SOURCE_URL).status_code == 200
