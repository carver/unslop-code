"""Spec section: Origin Allowlist -- the `Referer` gate in front of every route."""

import pytest
from helpers import post_upload

CSV = "name,age\nada,36\n"
ALLOWED = "https://app.example.com/reports"


def get(client, path, referer=None, **kwargs):
    headers = {"Referer": referer} if referer is not None else {}
    return client.get(path, headers=headers, **kwargs)


# Phrase: "No allowlist means all requests pass."
def test_without_an_allowlist_a_request_with_no_referer_passes(settings_client, origin):
    client = settings_client()
    source = origin.serve("/data.csv", CSV)

    assert get(client, f"/convert?source={source}").status_code == 200


# Phrase: "No allowlist means all requests pass."
# Context: an unrelated referer is not consulted either.
def test_without_an_allowlist_any_referer_passes(settings_client, origin):
    client = settings_client()
    source = origin.serve("/data.csv", CSV)

    assert get(client, f"/convert?source={source}", "https://evil.test/").status_code == 200


# Phrase: "1. Require `Referer`."
def test_a_missing_referer_is_forbidden(settings_client):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")

    response = get(client, "/convert?source=https://a.test/x")

    assert response.status_code == 403
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"]


# Phrase: "1. Require `Referer`."
# Context: an empty header carries no origin either.
def test_an_empty_referer_is_forbidden(settings_client):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")

    assert get(client, "/convert?source=https://a.test/x", "").status_code == 403


# Phrase: "3. Accept only hostnames matching any allowed suffix"
# Context: the suffix's own domain matches it (AMBIGUITIES T67).
def test_the_apex_domain_matches_its_own_suffix(settings_client, origin):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")
    source = origin.serve("/data.csv", CSV)

    assert get(client, f"/convert?source={source}", "https://example.com/p").status_code == 200


# Phrase: "3. Accept only hostnames matching any allowed suffix"
@pytest.mark.parametrize(
    "referer",
    [
        "https://app.example.com/reports",
        "https://deep.nested.example.com/",
        "http://app.example.com:8080/x",
        "https://app.example.com",
    ],
)
def test_subdomains_of_an_allowed_suffix_pass(settings_client, origin, referer):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")
    source = origin.serve("/data.csv", CSV)

    assert get(client, f"/convert?source={source}", referer).status_code == 200


# Phrase: "matching ... case-insensitively"
@pytest.mark.parametrize("referer", ["https://APP.EXAMPLE.COM/x", "https://Example.Com/x"])
def test_hostname_matching_folds_case(settings_client, origin, referer):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")
    source = origin.serve("/data.csv", CSV)

    assert get(client, f"/convert?source={source}", referer).status_code == 200


# Phrase: "matching ... case-insensitively"
# Context: the configured suffix is folded too.
def test_a_configured_suffix_is_matched_case_insensitively(settings_client, origin):
    client = settings_client(ORIGIN_ALLOWLIST="EXAMPLE.COM")
    source = origin.serve("/data.csv", CSV)

    assert get(client, f"/convert?source={source}", "https://app.example.com/x").status_code == 200


# Phrase: "with domain-boundary rules"
# Context: the match must land on a label boundary (AMBIGUITIES T67).
@pytest.mark.parametrize(
    "referer",
    [
        "https://notexample.com/x",
        "https://evil-example.com/x",
        "https://example.com.evil.test/x",
        "https://xexample.com/x",
    ],
)
def test_a_suffix_must_match_on_a_label_boundary(settings_client, referer):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")

    assert get(client, "/convert?source=https://a.test/x", referer).status_code == 403


# Phrase: "4. Otherwise return `HTTP 403`."
def test_a_host_outside_the_allowlist_is_forbidden(settings_client):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")

    response = get(client, "/convert?source=https://a.test/x", "https://other.test/x")

    assert response.status_code == 403
    assert set(response.get_json()) == {"ok", "error"}


# Phrase: "2. Parse hostname."
# Context: a referer with no parseable hostname is refused (AMBIGUITIES T66).
@pytest.mark.parametrize("referer", ["not-a-url", "example.com/path", "/relative/page"])
def test_a_referer_without_a_hostname_is_forbidden(settings_client, referer):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")

    assert get(client, "/convert?source=https://a.test/x", referer).status_code == 403


# Phrase: "Accept only hostnames matching any allowed suffix"
# Context: any one entry of the list is enough.
@pytest.mark.parametrize("host", ["a.test", "sub.b.test", "c.test"])
def test_any_entry_of_the_list_admits_a_host(settings_client, origin, host):
    client = settings_client(ORIGIN_ALLOWLIST="a.test,b.test,c.test")
    source = origin.serve("/data.csv", CSV)

    assert get(client, f"/convert?source={source}", f"https://{host}/p").status_code == 200


# Phrase: "check every request before routing"
# Context: the dataset routes are guarded too.
def test_the_dataset_route_is_guarded(settings_client, origin):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")
    source = origin.serve("/data.csv", CSV)
    endpoint = get(client, f"/convert?source={source}", ALLOWED).get_json()["endpoint"]

    assert get(client, endpoint, "https://other.test/").status_code == 403
    assert get(client, endpoint, ALLOWED).status_code == 200


# Phrase: "check every request before routing"
# Context: the export route is guarded too.
def test_the_export_route_is_guarded(settings_client, origin):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")
    source = origin.serve("/data.csv", CSV)
    endpoint = get(client, f"/convert?source={source}", ALLOWED).get_json()["endpoint"]

    assert get(client, endpoint + "/export", "https://other.test/").status_code == 403


# Phrase: "check every request before routing"
# Context: 403 outranks the 404 the path would otherwise get (AMBIGUITIES T65).
def test_an_unknown_path_is_forbidden_before_it_is_routed(settings_client):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")

    assert get(client, "/no/such/route", "https://other.test/").status_code == 403
    assert get(client, "/no/such/route", ALLOWED).status_code == 404


# Phrase: "check every request before routing"
# Context: `/upload` is guarded on the POST method as well (AMBIGUITIES T65).
def test_upload_is_guarded(settings_client):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")

    assert post_upload(client, CSV).status_code == 403
    assert post_upload(client, CSV, headers={"Referer": ALLOWED}).status_code == 200


# Phrase: "check every request before routing"
# Context: a preflight is a request like any other (AMBIGUITIES T65).
def test_a_preflight_is_guarded(settings_client):
    client = settings_client(ORIGIN_ALLOWLIST="example.com")

    assert client.options("/convert").status_code == 403


# Phrase: "check every request before routing"
# Context: the allowlist runs ahead of the size check (AMBIGUITIES T73).
def test_the_allowlist_outranks_the_size_limit(settings_client):
    client = settings_client(ORIGIN_ALLOWLIST="example.com", MAX_SOURCE_SIZE="1")

    assert post_upload(client, CSV).status_code == 403


# Phrase: "If configured, check every request"
# Context: an entry written with a leading dot behaves the same (AMBIGUITIES T64).
def test_a_suffix_written_with_a_leading_dot(settings_client, origin):
    client = settings_client(ORIGIN_ALLOWLIST=".example.com")
    source = origin.serve("/data.csv", CSV)

    assert get(client, f"/convert?source={source}", ALLOWED).status_code == 200
    assert get(client, f"/convert?source={source}", "https://other.test/").status_code == 403
