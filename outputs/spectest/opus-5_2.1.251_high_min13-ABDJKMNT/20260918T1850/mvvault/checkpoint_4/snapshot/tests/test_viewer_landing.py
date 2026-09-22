"""Spec sections: `/` Routes, `/` Recent Vaults."""

import re

from conftest import is_redirect, v1_catalog, v1_entry, v3_catalog, v3_entry, write_vault


def recent_links(html):
    """Hrefs of the landing page's recent-vault links, in page order."""
    return [href for href in re.findall(r'<a href="([^"]+)"', html) if href.startswith("/catalog/")]


# Spec: `GET` `/` | HTML page containing a form input for vault name
def test_landing_page_is_html(serve):
    response = serve().get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]


# Spec: `GET` `/` | HTML page containing a form input for vault name
def test_landing_page_has_a_vault_name_input(serve):
    body = serve().get("/").text
    assert "<form" in body
    assert 'name="catalog"' in body


# Spec: `POST` `/` | redirect to `/catalog/<value>` when `catalog` field is present
def test_post_redirects_to_the_named_vault(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    assert is_redirect(serve().post({"catalog": "vault"}), "/catalog/vault")


# Spec: `POST` `/` | Accept form-encoded body
def test_post_accepts_a_form_encoded_body_for_an_unknown_vault(serve):
    assert serve().post({"catalog": "ghost"}).status_code in (302, 303)


# Spec: `POST` `/` | otherwise redirect to `/`
# Spec: Missing `catalog` field on `POST /` | Redirect to `/`
def test_post_without_the_catalog_field_redirects_to_the_landing_page(serve):
    assert is_redirect(serve().post({"other": "vault"}), "/")


# Spec: Redirect status | HTTP `302` or `303`
def test_post_redirect_uses_a_redirect_status(serve, tmp_path):
    write_vault(tmp_path, v3_catalog())
    assert serve().post({"catalog": "vault"}).status_code in (302, 303)


# Spec: Empty state | Area may be empty or absent
def test_landing_page_works_with_nothing_visited_yet(serve):
    response = serve().get("/")
    assert response.status_code == 200
    assert recent_links(response.text) == []


# Spec: Trigger | Navigation to any vault through viewer
# Spec: Display location | Landing page
def test_visited_vault_appears_on_the_landing_page(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    viewer = serve()
    viewer.get("/catalog/vault/episodes")
    assert "vault" in viewer.get("/").text


# Spec: Link target | Each recent-vault link points directly to that vault's
# resolved default category page
def test_recent_link_targets_the_default_category_page(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    viewer = serve()
    viewer.get("/catalog/vault")
    assert recent_links(viewer.get("/").text) == ["/catalog/vault/episodes"]


# Spec: Recent-vault links on `/` | Use the same resolved default-category route
# as `/catalog/<name>` would redirect to (version-aware)
def test_recent_link_for_a_v1_vault_points_at_entries(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    viewer = serve()
    viewer.get("/catalog/vault")
    assert recent_links(viewer.get("/").text) == ["/catalog/vault/entries"]


# Spec: Ordering | Most recently visited first
def test_recent_vaults_are_listed_most_recent_first(serve, tmp_path):
    for name in ("one", "two", "three"):
        write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]), name=name)
    viewer = serve()
    for name in ("one", "two", "three"):
        viewer.get(f"/catalog/{name}/episodes")

    links = recent_links(viewer.get("/").text)
    assert links == [
        "/catalog/three/episodes",
        "/catalog/two/episodes",
        "/catalog/one/episodes",
    ]


# Spec: Recent-vault order | Most recently visited first (re-visiting moves a
# vault back to the front)
def test_revisiting_a_vault_moves_it_to_the_front(serve, tmp_path):
    for name in ("one", "two"):
        write_vault(tmp_path, v3_catalog(), name=name)
    viewer = serve()
    viewer.get("/catalog/one/episodes")
    viewer.get("/catalog/two/episodes")
    viewer.get("/catalog/one/episodes")

    assert recent_links(viewer.get("/").text) == [
        "/catalog/one/episodes",
        "/catalog/two/episodes",
    ]


# Spec: Persistence | Later browser session from same browser must still show
# visited vault
def test_recent_vaults_survive_a_new_browser_session(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    viewer = serve()
    viewer.get("/catalog/vault/episodes")

    viewer.reopen(cookies=viewer.cookies)
    assert "/catalog/vault/episodes" in recent_links(viewer.get("/").text)


# Spec: Persistence | ... the browser keeps the list beyond the current session
def test_recent_vaults_are_stored_beyond_the_browser_session(serve, tmp_path):
    write_vault(tmp_path, v3_catalog())
    viewer = serve()
    header = viewer.get("/catalog/vault/episodes").headers.get("Set-Cookie", "")
    assert "Max-Age" in header or "Expires" in header


# Spec: `POST` `/` | redirect to `/catalog/<value>` when `catalog` field is
# present, otherwise redirect to `/` (an empty value names no vault)
def test_post_with_an_empty_catalog_value_redirects_to_the_landing_page(serve):
    assert is_redirect(serve().post({"catalog": "  "}), "/")
