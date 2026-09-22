"""Spec section: HTTP Error Handling, for the detail and static file routes."""

from conftest import (
    add_media,
    assert_clean,
    is_redirect,
    v1_catalog,
    v1_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)


# Spec: Missing entry in specified category | HTTP `404`, or redirect to
# category listing with error indication
def test_missing_entry_is_refused_or_redirected(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/episodes/nope")
    assert response.status_code in (302, 303, 404)
    if response.status_code in (302, 303):
        assert is_redirect(response, "/catalog/vault/episodes")
    assert_clean(response)


# Spec: Missing entry in specified category | ... (an empty category has none)
def test_entry_route_on_an_empty_category_is_refused_or_redirected(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    assert serve().get("/catalog/vault/clips/e1").status_code in (302, 303, 404)


# Spec: Non-existent vault on detail or static route | Redirect to landing page
# with vault-not-found indication
def test_detail_route_on_a_missing_vault_redirects_to_the_landing_page(serve):
    assert is_redirect(serve().get("/catalog/ghost/episodes/e1"), "/")


# Spec: ... with vault-not-found indication
def test_detail_route_on_a_missing_vault_names_it_on_the_landing_page(serve):
    body = serve().get("/catalog/ghost/episodes/e1", follow=True).text
    assert "ghost" in body
    assert "not found" in body.lower()


# Spec: Invalid category on detail route | Same handling allowed for invalid
# category listing route
def test_invalid_category_on_a_detail_route(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/nope/e1")
    assert response.status_code in (302, 303, 400, 404)
    if response.status_code in (302, 303):
        assert is_redirect(response, "/catalog/vault/episodes")
    assert_clean(response)


# Spec: Invalid category on detail route | ... (a v1 vault has only `entries`)
def test_invalid_category_on_a_v1_detail_route(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = serve().get("/catalog/vault/episodes/e1")
    assert response.status_code in (302, 303, 400, 404)
    if response.status_code in (302, 303):
        assert is_redirect(response, "/catalog/vault/entries")


# Spec: Any HTTP error | Well-formed response; no raw stack trace or internal
# detail exposure
def test_errors_on_these_routes_stay_well_formed(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    add_media(vault_dir, "e1.mp4")
    viewer = serve()
    for path in (
        "/catalog/vault/episodes/nope",
        "/vault/vault/media/missing.mp4",
        "/vault/vault/media/..%2Fcatalog.json",
        "/vault/vault/preview/e1",
        "/vault/ghost/media/e1.mp4",
        "/vault/vault/nowhere/e1",
        "/vault/vault",
    ):
        assert_clean(viewer.get(path))


# Spec: Any HTTP error | ... no raw stack trace (an unreadable catalog)
def test_static_route_on_an_unreadable_vault_is_not_a_server_error(serve, tmp_path):
    write_vault(tmp_path, "{ not json")
    assert_clean(serve().get("/vault/vault/media/e1.mp4", follow=True))
