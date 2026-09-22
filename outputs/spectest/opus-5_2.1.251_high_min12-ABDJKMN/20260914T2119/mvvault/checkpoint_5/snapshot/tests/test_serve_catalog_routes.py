"""Spec: `/catalog` Routes, Version-Aware Default Category Redirect and
Version-Aware Valid Categories."""
import pytest

from digest_helpers import v1, v1_entry, v2, v3, v3_entry, legacy_entry
from viewer_helpers import hrefs


# Spec: "| `GET` | `/catalog/<name>` | Redirect to default category page for
# vault |" + "| v3 | `/catalog/<name>/episodes` |"
def test_catalog_name_redirects_v3_to_episodes(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get("/catalog/vault")
    assert response.is_redirect, response
    assert response.location == "/catalog/vault/episodes"


# Spec: "| v2 | `/catalog/<name>/episodes` |"
def test_catalog_name_redirects_v2_to_episodes(serve, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    response = serve().get("/catalog/vault")
    assert response.location == "/catalog/vault/episodes"


# Spec: "| v1 | `/catalog/<name>/entries` |"
def test_catalog_name_redirects_v1_to_entries(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    response = serve().get("/catalog/vault")
    assert response.location == "/catalog/vault/entries"


# Spec: "| Redirect status | HTTP `302` or `303` |"
def test_default_category_redirect_status(serve, make_vault):
    make_vault(v3())
    assert serve().get("/catalog/vault").status in (302, 303)


# Spec: "| `GET` | `/catalog/<name>/<category>` | HTML listing for category |"
def test_category_page_is_html(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep One")]))
    response = serve().get("/catalog/vault/episodes")
    assert response.status == 200, response
    assert "<html" in response.body.lower()
    assert "Ep One" in response.body


# Spec: "| v2 | `episodes`, `streams`, `clips` |" -- all three are valid.
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_valid_categories(serve, make_vault, category):
    make_vault(v2(**{category: [legacy_entry(id="x1", title="Only")]}))
    response = serve().get("/catalog/vault/%s" % category)
    assert response.status == 200, response
    assert "Only" in response.body


# Spec: "| v3 | `episodes`, `streams`, `clips` |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_valid_categories(serve, make_vault, category):
    make_vault(v3(**{category: [v3_entry(id="x1", title="Only")]}))
    response = serve().get("/catalog/vault/%s" % category)
    assert response.status == 200, response
    assert "Only" in response.body


# Spec: "| v1 | `entries` |" -- the flat v1 list is served as `entries`.
def test_v1_entries_category(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title="Flat")]))
    response = serve().get("/catalog/vault/entries")
    assert response.status == 200, response
    assert "Flat" in response.body


# Spec: "| v1 | `entries` |" -- `episodes` is not a v1 category, so it is
# handled by the invalid-category rule rather than served.
def test_v1_episodes_is_not_a_valid_category(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    response = serve().get("/catalog/vault/episodes")
    assert response.status in (302, 303, 400, 404), response
    if response.is_redirect:
        assert response.location == "/catalog/vault/entries"


# Spec: "| v2 | `episodes`, `streams`, `clips` |" -- `entries` is not one of
# them.
def test_v2_entries_is_not_a_valid_category(serve, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    response = serve().get("/catalog/vault/entries")
    assert response.status in (302, 303, 400, 404), response
    if response.is_redirect:
        assert response.location == "/catalog/vault/episodes"


# Spec: "| `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for
# matching entry |"
def test_entry_route_returns_html(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Target")]))
    response = serve().get("/catalog/vault/episodes/e1")
    assert response.status == 200, response
    assert "<html" in response.body.lower()
    assert "Target" in response.body


# Spec: "| ... | Entry detail page for matching entry |" -- the detail page is
# a page of its own, not the category listing.
def test_entry_route_surfaces_the_requested_entry(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="One"),
                            v3_entry(id="e2", title="Two")]))
    server = serve()
    listing = server.get("/catalog/vault/episodes").body
    entry = server.get("/catalog/vault/episodes/e2").body
    assert entry != listing


# Spec: the entry route works for every valid category of a v3 vault.
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_entry_route_for_each_v3_category(serve, make_vault, category):
    make_vault(v3(**{category: [v3_entry(id="x1", title="Named")]}))
    response = serve().get("/catalog/vault/%s/x1" % category)
    assert response.status == 200, response
    assert "Named" in response.body


# Spec: the entry route works for v1's `entries` category.
def test_entry_route_for_v1(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title="Flat")]))
    response = serve().get("/catalog/vault/entries/e1")
    assert response.status == 200, response
    assert "Flat" in response.body


# Spec: "| `GET` | `/catalog/<name>` | Redirect to default category page ... |"
# -- following the redirect reaches the listing itself.
def test_catalog_name_redirect_is_followable(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep One")]))
    response = serve().get("/catalog/vault", follow=True)
    assert response.status == 200, response
    assert "Ep One" in response.body


# Spec: "| Entry navigation | Each listed entry includes a link to
# `/catalog/<name>/<category>/<id>` |" -- reachable from the listing page.
def test_listing_links_reach_entry_pages(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="One")]))
    server = serve()
    body = server.get("/catalog/vault/episodes").body
    assert "/catalog/vault/episodes/e1" in hrefs(body)
    assert server.get("/catalog/vault/episodes/e1").status == 200
