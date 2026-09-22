"""Spec section: HTTP Error Handling."""

from conftest import (
    is_redirect,
    v1_catalog,
    v1_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

#: Wording every error response is checked against for leaked internals.
LEAKS = ("Traceback", "File \"", "Exception")


def assert_clean(response):
    """A well-formed HTTP response with no raw exception text in it."""
    assert response.status_code != 500
    assert "Content-Type" in response.headers
    for leak in LEAKS:
        assert leak not in response.text


# Spec: Invalid category on `GET /catalog/<name>/<category>` for v1 vault |
# Redirect to `/catalog/<name>/entries` or return HTTP `400`/`404`
def test_invalid_category_on_a_v1_vault(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = serve().get("/catalog/vault/clips")
    assert response.status_code in (302, 303, 400, 404)
    if response.status_code in (302, 303):
        assert is_redirect(response, "/catalog/vault/entries")
    assert_clean(response)


# Spec: Invalid category on `GET /catalog/<name>/<category>` for v2/v3 vault |
# Redirect to `/catalog/<name>/episodes` or return HTTP `400`/`404`
def test_invalid_category_on_a_v3_vault(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/nope")
    assert response.status_code in (302, 303, 400, 404)
    if response.status_code in (302, 303):
        assert is_redirect(response, "/catalog/vault/episodes")
    assert_clean(response)


# Spec: Non-existent vault on any `/catalog/<name>` route | Redirect to `/`
def test_missing_vault_on_the_catalog_route_redirects_home(serve):
    response = serve().get("/catalog/ghost")
    assert is_redirect(response, "/")
    assert_clean(response)


# Spec: Non-existent vault on any `/catalog/<name>` route | Redirect to `/`
def test_missing_vault_on_a_category_route_redirects_home(serve):
    assert is_redirect(serve().get("/catalog/ghost/episodes"), "/")


# Spec: Non-existent vault on any `/catalog/<name>` route | Redirect to `/`
def test_missing_vault_on_an_entry_route_redirects_home(serve):
    assert is_redirect(serve().get("/catalog/ghost/episodes/e1"), "/")


# Spec: ... landing page shows vault-not-found indication
def test_landing_page_reports_the_missing_vault(serve):
    body = serve().get("/catalog/ghost", follow=True).text
    assert "ghost" in body
    assert "not found" in body.lower()


# Spec: ... response must not be HTTP `500`
def test_missing_vault_is_never_a_server_error(serve):
    assert_clean(serve().get("/catalog/ghost/episodes", follow=True))


# Spec: Non-existent vault | a directory without a catalog is not a vault either
def test_directory_without_a_catalog_is_not_found(serve, tmp_path):
    (tmp_path / "empty").mkdir()
    assert is_redirect(serve().get("/catalog/empty"), "/")


# Spec: Any HTTP error | Well-formed HTTP response; no raw exception or stack
# trace exposure
def test_unreadable_catalog_is_not_a_server_error(serve, tmp_path):
    write_vault(tmp_path, "{ not json")
    assert_clean(serve().get("/catalog/vault", follow=True))


# Spec: Any HTTP error | Well-formed HTTP response
def test_unsupported_catalog_version_is_not_a_server_error(serve, tmp_path):
    write_vault(tmp_path, {"version": 9, "source": "http://x.invalid", "episodes": []})
    assert_clean(serve().get("/catalog/vault", follow=True))


# Spec: Any HTTP error | Well-formed HTTP response
def test_unknown_path_is_answered_cleanly(serve):
    response = serve().get("/nowhere")
    assert response.status_code == 404
    assert_clean(response)


# Spec: Any HTTP error | ... a vault name may not escape the viewer's directory
def test_traversing_out_of_the_vault_directory_is_refused(serve):
    assert_clean(serve().get("/catalog/..%2F..%2Fetc/episodes"))


# Spec: Any HTTP error | Well-formed HTTP response (unknown entry id)
def test_unknown_entry_id_is_answered_cleanly(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    assert_clean(serve().get("/catalog/vault/episodes/nope"))


# Spec: Non-existent vault on any `/catalog/<name>` route | Redirect to `/`
# (a catalog route with no vault name names no vault at all)
def test_catalog_route_without_a_name_redirects_home(serve):
    assert is_redirect(serve().get("/catalog/"), "/")


# Spec: Any HTTP error | Well-formed HTTP response (a route deeper than an entry)
def test_route_below_an_entry_is_answered_cleanly(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/episodes/e1/extra")
    assert response.status_code == 404
    assert_clean(response)
