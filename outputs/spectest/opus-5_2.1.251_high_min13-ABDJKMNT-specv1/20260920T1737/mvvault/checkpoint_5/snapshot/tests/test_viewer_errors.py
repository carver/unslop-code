"""Spec section: HTTP Error Handling."""

from conftest import (
    EPOCH_KEY,
    REDIRECT_STATUSES,
    legacy_entry,
    v1_catalog,
    v3_catalog,
    v3_entry,
    write_vault,
)

ERROR_STATUSES = (400, 404)


def assert_clean(response):
    """A response the spec calls well-formed: no exception text in the body."""
    assert "Traceback" not in response.body
    assert "most recent call last" not in response.body


# Spec: "| Invalid category on `GET /catalog/<name>/<category>` for v1 vault |
# Redirect to `/catalog/<name>/entries` or return HTTP `400`/`404` |".
def test_invalid_category_on_v1_vault(viewer, tmp_path):
    write_vault(tmp_path, "demo", v1_catalog(legacy_entry("e1", EPOCH_KEY)))

    response = viewer.client.get("/catalog/demo/clips")

    assert_clean(response)
    if response.status in REDIRECT_STATUSES:
        assert response.location == "/catalog/demo/entries"
    else:
        assert response.status in ERROR_STATUSES


# Spec: "| Invalid category on `GET /catalog/<name>/<category>` for v2/v3 vault
# | Redirect to `/catalog/<name>/episodes` or return HTTP `400`/`404` |".
def test_invalid_category_on_v3_vault(viewer, tmp_path):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")]))

    response = viewer.client.get("/catalog/demo/entries")

    assert_clean(response)
    if response.status in REDIRECT_STATUSES:
        assert response.location == "/catalog/demo/episodes"
    else:
        assert response.status in ERROR_STATUSES


# Spec: "| Non-existent vault on any `/catalog/<name>` route | Redirect to `/`;
# ... response must not be HTTP `500` |".
def test_non_existent_vault_redirects_to_the_landing_page(viewer):
    for path in ("/catalog/ghost", "/catalog/ghost/episodes", "/catalog/ghost/episodes/e1"):
        response = viewer.client.get(path)

        assert response.status != 500
        assert response.status in REDIRECT_STATUSES
        assert response.location == "/"


# Spec: "| Non-existent vault ... | ... landing page shows vault-not-found
# indication ... |".
def test_landing_page_reports_the_missing_vault(viewer):
    viewer.client.get("/catalog/ghost")

    body = viewer.client.get("/").body

    assert "ghost" in body
    assert "not found" in body.lower()


# Spec: "| Missing `catalog` field on `POST /` | Redirect to `/` |".
def test_post_without_catalog_field_redirects_to_root(viewer):
    response = viewer.client.post("/", {})

    assert response.status in REDIRECT_STATUSES
    assert response.location == "/"


# Spec: "| Any HTTP error | Well-formed HTTP response; no raw exception or
# stack trace exposure |" -- an unrouted path is answered, not dropped.
def test_unknown_path_is_a_clean_error(viewer):
    response = viewer.client.get("/no/such/place")

    assert response.status in ERROR_STATUSES
    assert_clean(response)


# Spec: "| Any HTTP error | Well-formed HTTP response; no raw exception or
# stack trace exposure |" -- an unreadable catalog is not a crash either.
def test_unreadable_catalog_is_a_clean_response(viewer, tmp_path):
    write_vault(tmp_path, "broken", "{not json")

    response = viewer.client.get("/catalog/broken/episodes")

    assert response.status != 500
    assert_clean(response)


# Spec: "| Any HTTP error | Well-formed HTTP response ... |" -- a vault name
# that escapes the served directory is answered like any unknown vault.
def test_path_traversal_name_is_not_a_crash(viewer):
    response = viewer.client.get("/catalog/%2e%2e%2fetc/episodes")

    assert response.status != 500
    assert_clean(response)
