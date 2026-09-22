"""`ORIGIN_ALLOWLIST`: which requests are allowed to reach the routes at all."""

import io

import pytest

BODY = "name,age\nada,36\n"
ALLOWED = "https://app.example.com/reports?tab=1"


def get(client, path, referer=None, **kwargs):
    """GET `path`, sending `referer` as the `Referer` header when given."""
    headers = {} if referer is None else {"Referer": referer}
    return client.get(path, headers=headers, **kwargs)


def allowlisted_client(configured_client, *suffixes):
    return configured_client(ORIGIN_ALLOWLIST=",".join(suffixes))


# Spec: "No allowlist means all requests pass."
# Context: the default configuration, with no `Referer` on the request.
def test_without_an_allowlist_a_refererless_request_passes(client, convert):
    assert convert(BODY).status_code == 200


# Spec: "If configured, check every request before routing: 1. Require
# `Referer`."
# Context: an allowlist is configured and the request carries no `Referer`.
def test_a_missing_referer_is_refused(configured_client, origin):
    client = allowlisted_client(configured_client, "example.com")
    response = get(client, "/convert", query_string={"source": origin.url("/x.csv")})
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


# Spec: "| Missing `Referer` (allowlist active) | 403 | `{"ok": false, "error":
# "<message>"}` |"
# Context: the refusal carries the standard envelope with a message.
def test_the_refusal_uses_the_standard_envelope(configured_client):
    client = allowlisted_client(configured_client, "example.com")
    payload = get(client, "/convert").get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# Spec: "1. Require `Referer`."
# Context: a header that is present but empty says no more than an absent one.
def test_an_empty_referer_is_refused(configured_client):
    client = allowlisted_client(configured_client, "example.com")
    assert get(client, "/convert", referer="").status_code == 403


# Spec: "3. Accept only hostnames matching any allowed suffix"
# Context: a `Referer` on the allowlisted domain itself reaches the route, which
# then answers on its own merits.
def test_an_allowed_referer_reaches_the_route(configured_client, origin):
    client = allowlisted_client(configured_client, "example.com")
    source = origin.serve("/allowlist-ok.csv", BODY)
    response = get(
        client, "/convert", referer="https://example.com/page", query_string={"source": source}
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# Spec: "2. Parse hostname. 3. Accept only hostnames matching any allowed
# suffix ... with domain-boundary rules."
# Context: hostnames under the allowed domain, at the boundary and past it (T61).
@pytest.mark.parametrize(
    "referer,allowed",
    [
        ("https://example.com/", True),
        ("https://app.example.com/", True),
        ("https://deep.app.example.com/", True),
        ("https://notexample.com/", False),
        ("https://example.com.evil.net/", False),
        ("https://examplexcom/", False),
        ("https://example.org/", False),
    ],
)
def test_domain_boundary_rules(configured_client, referer, allowed):
    client = allowlisted_client(configured_client, "example.com")
    assert (get(client, "/convert", referer=referer).status_code == 403) is not allowed


# Spec: "Accept only hostnames matching any allowed suffix case-insensitively"
# Context: the header's case and the configured suffix's case both vary.
@pytest.mark.parametrize("referer", ["https://EXAMPLE.com/", "https://App.Example.COM/"])
def test_matching_is_case_insensitive(configured_client, referer):
    client = allowlisted_client(configured_client, "Example.COM")
    assert get(client, "/convert", referer=referer).status_code != 403


# Spec: "matching any allowed suffix"
# Context: several suffixes configured; a host under either one is accepted.
def test_any_configured_suffix_matches(configured_client):
    client = allowlisted_client(configured_client, "a.test", "b.test")
    assert get(client, "/convert", referer="https://x.b.test/p").status_code != 403
    assert get(client, "/convert", referer="https://c.test/p").status_code == 403


# Spec: "list of domain suffixes"
# Context: a suffix written with a leading dot means the same domain (T61).
def test_a_leading_dot_suffix_matches_the_apex_and_below(configured_client):
    client = allowlisted_client(configured_client, ".example.com")
    assert get(client, "/convert", referer="https://example.com/p").status_code != 403
    assert get(client, "/convert", referer="https://api.example.com/p").status_code != 403


# Spec: "2. Parse hostname."
# Context: the port and the rest of the URL are not part of the hostname (T62).
@pytest.mark.parametrize(
    "referer",
    [
        "http://example.com:8443/page",
        "https://example.com./page",
        "https://user:pw@example.com/page",
    ],
)
def test_only_the_hostname_is_compared(configured_client, referer):
    client = allowlisted_client(configured_client, "example.com")
    assert get(client, "/convert", referer=referer).status_code != 403


# Spec: "2. Parse hostname. ... 4. Otherwise return `HTTP 403`."
# Context: a `Referer` no hostname can be parsed out of (T60).
@pytest.mark.parametrize("referer", ["not a url", "/relative/page", "about:blank"])
def test_a_referer_without_a_hostname_is_refused(configured_client, referer):
    client = allowlisted_client(configured_client, "example.com")
    assert get(client, "/convert", referer=referer).status_code == 403


# Spec: "check every request before routing"
# Context: the dataset read and export routes are guarded too (T59).
def test_dataset_routes_are_guarded(configured_client, origin, tmp_path):
    storage = str(tmp_path / "shared")
    open_client = configured_client(STORAGE_DIR=storage)
    source = origin.serve("/allowlist-guarded.csv", BODY)
    endpoint = open_client.get(
        "/convert", query_string={"source": source}
    ).get_json()["endpoint"]
    client = configured_client(ORIGIN_ALLOWLIST="example.com", STORAGE_DIR=storage)
    assert get(client, endpoint).status_code == 403
    assert get(client, f"{endpoint}/export").status_code == 403
    assert get(client, endpoint, referer="https://example.com/").status_code == 200


# Spec: "check every request before routing"
# Context: the check precedes the route lookup, so an unknown path is refused
# rather than reported as missing (T59).
def test_an_unknown_path_is_refused_before_it_is_matched(configured_client):
    client = allowlisted_client(configured_client, "example.com")
    assert get(client, "/nothing-here").status_code == 403


# Spec: "check every request before routing"
# Context: every method, including an upload and a CORS preflight (T59).
def test_other_methods_are_guarded(configured_client):
    client = allowlisted_client(configured_client, "example.com")
    upload = client.post(
        "/upload",
        data={"file": (io.BytesIO(BODY.encode()), "t.csv")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 403
    assert client.options("/convert").status_code == 403
