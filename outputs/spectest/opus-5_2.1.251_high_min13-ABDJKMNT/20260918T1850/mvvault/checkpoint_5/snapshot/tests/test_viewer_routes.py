"""Spec sections: `/catalog` Routes, Version-Aware Default Category Redirect,
Version-Aware Valid Categories."""

import pytest

from conftest import (
    is_redirect,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)


# Spec: `GET` `/catalog/<name>` | Redirect to default category page for vault
# Spec: v3 | `/catalog/<name>/episodes`
def test_catalog_redirects_to_the_default_category(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    assert is_redirect(serve().get("/catalog/vault"), "/catalog/vault/episodes")


# Spec: Redirect status | HTTP `302` or `303`
def test_catalog_redirect_uses_a_redirect_status(serve, tmp_path):
    write_vault(tmp_path, v3_catalog())
    assert serve().get("/catalog/vault").status_code in (302, 303)


# Spec: v1 | `/catalog/<name>/entries`
def test_v1_default_category_is_entries(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    assert is_redirect(serve().get("/catalog/vault"), "/catalog/vault/entries")


# Spec: v2 | `/catalog/<name>/episodes`
def test_v2_default_category_is_episodes(serve, tmp_path):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")]))
    assert is_redirect(serve().get("/catalog/vault"), "/catalog/vault/episodes")


# Spec: `GET` `/catalog/<name>/<category>` | HTML listing for category
def test_category_listing_is_html(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/episodes")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "Title e1" in response.text


# Spec: `GET` `/catalog/<name>/<category>/<id>` | HTML response for that viewer
# link target
def test_entry_route_answers_with_html(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/episodes/e1")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]


# Spec: ... may reuse the category listing page with the entry highlighted or
# otherwise surfaced
def test_entry_route_surfaces_the_entry(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1"), v3_entry("e2")]))
    viewer = serve()
    listing = viewer.get("/catalog/vault/episodes").text
    surfaced = viewer.get("/catalog/vault/episodes/e2").text
    assert "Title e2" in surfaced
    assert surfaced != listing


# Spec: v2 | `episodes`, `streams`, `clips`
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_categories_are_all_valid(serve, tmp_path, category):
    write_vault(tmp_path, v2_catalog(**{category: [v2_entry("x1")]}))
    assert serve().get(f"/catalog/vault/{category}").status_code == 200


# Spec: v3 | `episodes`, `streams`, `clips`
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_categories_are_all_valid(serve, tmp_path, category):
    write_vault(tmp_path, v3_catalog(**{category: [v3_entry("x1")]}))
    assert serve().get(f"/catalog/vault/{category}").status_code == 200


# Spec: v1 | `entries`
def test_v1_entries_category_is_valid(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = serve().get("/catalog/vault/entries")
    assert response.status_code == 200
    assert "Title e1" in response.text


# Spec: Valid categories | Version-dependent: v1 uses `entries`
def test_v1_vault_has_no_episodes_category(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = serve().get("/catalog/vault/episodes")
    assert response.status_code in (302, 303, 400, 404)


# Spec: Valid categories | ... v2/v3 use `episodes`, `streams`, `clips`
def test_v3_vault_has_no_entries_category(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/entries")
    assert response.status_code in (302, 303, 400, 404)


# Spec: Category matching | Case-sensitive
def test_category_matching_is_case_sensitive(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/Episodes")
    assert response.status_code in (302, 303, 400, 404)
