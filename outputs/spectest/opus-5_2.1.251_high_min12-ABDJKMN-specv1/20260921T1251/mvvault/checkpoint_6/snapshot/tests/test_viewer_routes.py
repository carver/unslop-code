"""Spec section: `/` Routes / `/catalog` Routes / Version-Aware Redirect."""

from __future__ import annotations

import re

REDIRECTS = (302, 303)


def html_forms(body):
    return re.findall(r"<form\b.*?</form>", body, re.IGNORECASE | re.DOTALL)


def inputs(body):
    return re.findall(r"<(?:input|textarea)\b[^>]*>", body, re.IGNORECASE)


# ---------------------------------------------------------------------------
# | `GET` | `/` | HTML page containing a form input for vault name |
# ---------------------------------------------------------------------------

# Spec: | `GET` | `/` | HTML page ... |
def test_get_root_is_ok(serve):
    assert serve().client.get("/").status == 200


# Spec: | `GET` | `/` | HTML page ... |
# Context: "HTML page" - the response is served as HTML.
def test_get_root_serves_html(serve):
    response = serve().client.get("/")
    assert "html" in response.headers.get("Content-Type", "").lower()
    assert "<html" in response.body.lower()


# Spec: | `GET` | `/` | HTML page containing a form input for vault name |
def test_get_root_contains_a_form(serve):
    response = serve().client.get("/")
    assert html_forms(response.body), response.body


# Spec: | `GET` | `/` | ... a form input for vault name |
def test_get_root_form_has_an_input(serve):
    form = html_forms(serve().client.get("/").body)[0]
    assert inputs(form), form


# Spec: | `POST` | `/` | ... redirect to `/catalog/<value>` when `catalog` field
#   is present ... |
# Context: the landing form must submit the vault name under that field name.
def test_get_root_input_is_named_catalog(serve):
    form = html_forms(serve().client.get("/").body)[0]
    assert re.search(r"name\s*=\s*[\"']?catalog[\"']?", form, re.IGNORECASE), form


# ---------------------------------------------------------------------------
# | `POST` | `/` | Accept form-encoded body; redirect to `/catalog/<value>`
#   when `catalog` field is present, otherwise redirect to `/` |
# ---------------------------------------------------------------------------

# Spec: | `POST` | `/` | Accept form-encoded body; redirect to `/catalog/<value>` ... |
def test_post_root_redirects_to_the_named_catalog(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.post("/", {"catalog": "vault"})
    assert response.status in REDIRECTS, response.status
    assert response.location.endswith("/catalog/vault"), response.location


# Spec: | `POST` | `/` | ... redirect to `/catalog/<value>` ... |
# Context: the redirect is to the catalog route even when no such vault exists;
# that route decides what to do about a missing vault.
def test_post_root_redirect_does_not_require_an_existing_vault(serve):
    response = serve().client.post("/", {"catalog": "ghost"})
    assert response.status in REDIRECTS
    assert response.location.endswith("/catalog/ghost"), response.location


# Spec: | `POST` | `/` | Accept form-encoded body ... |
# Context: a form-encoded body is what a browser sends for the landing form.
def test_post_root_accepts_form_encoded_body(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    process = serve()
    response = process.client.request("POST", "/", body="catalog=vault")
    assert response.status in REDIRECTS, response.body


# Spec: | `POST` | `/` | ... otherwise redirect to `/` |
def test_post_root_without_catalog_field_redirects_to_root(serve):
    response = serve().client.post("/", {"other": "vault"})
    assert response.status in REDIRECTS
    assert response.location.split("?")[0].endswith("/"), response.location


# Spec: | Missing `catalog` field on `POST /` | Redirect to `/` |
def test_post_root_with_empty_body_redirects_to_root(serve):
    response = serve().client.request("POST", "/", body="")
    assert response.status in REDIRECTS
    assert response.location.split("?")[0].endswith("/"), response.location


# Spec: | Missing `catalog` field on `POST /` | Redirect to `/` |
# Context: following that redirect lands back on the landing page.
def test_post_root_without_catalog_field_lands_on_landing_page(serve):
    response = serve().client.post("/", {"other": "x"}, follow=True)
    assert response.status == 200
    assert html_forms(response.body), response.body


# Spec: | Redirect status | HTTP `302` or `303` | (Determinism)
def test_post_root_redirect_uses_302_or_303(serve, make_vault, catalogs):
    make_vault(catalogs.catalog())
    assert serve().client.post("/", {"catalog": "vault"}).status in REDIRECTS


# ---------------------------------------------------------------------------
# | `GET` | `/catalog/<name>` | Redirect to default category page for vault |
# ---------------------------------------------------------------------------

# Spec: | `GET` | `/catalog/<name>` | Redirect to default category page for vault |
def test_catalog_name_redirects(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault")
    assert response.status in REDIRECTS, response.status


# Spec: | v3 | `/catalog/<name>/episodes` | (Version-Aware Default Category Redirect)
def test_v3_default_category_redirect_is_episodes(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault")
    assert response.location.endswith("/catalog/vault/episodes"), response.location


# Spec: | v2 | `/catalog/<name>/episodes` |
def test_v2_default_category_redirect_is_episodes(serve, make_vault, legacy):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    response = serve().client.get("/catalog/vault")
    assert response.location.endswith("/catalog/vault/episodes"), response.location


# Spec: | v1 | `/catalog/<name>/entries` |
def test_v1_default_category_redirect_is_entries(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    response = serve().client.get("/catalog/vault")
    assert response.location.endswith("/catalog/vault/entries"), response.location


# Spec: | Redirect status | HTTP `302` or `303` |
def test_catalog_redirect_status_is_302_or_303(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert serve().client.get("/catalog/vault").status in REDIRECTS


# Spec: "The viewer works on vaults of any supported version without requiring
#   prior migration."
# Context: browsing a v1 vault must not rewrite its catalog.
def test_viewer_does_not_migrate_the_vault(serve, make_vault, legacy, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    before = (workdir / "vault" / "catalog.json").read_bytes()
    client = serve().client
    client.get("/catalog/vault", follow=True)
    client.get("/catalog/vault/entries")
    assert (workdir / "vault" / "catalog.json").read_bytes() == before


# ---------------------------------------------------------------------------
# | `GET` | `/catalog/<name>/<category>` | HTML listing for category |
# ---------------------------------------------------------------------------

# Spec: | `GET` | `/catalog/<name>/<category>` | HTML listing for category |
def test_category_listing_is_ok_html(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault/episodes")
    assert response.status == 200, response.status
    assert "html" in response.headers.get("Content-Type", "").lower()


# Spec: | v2 | `episodes`, `streams`, `clips` | (Version-Aware Valid Categories)
def test_v2_valid_categories_all_listed(serve, make_vault, legacy):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")],
                                 streams=[legacy.v2_entry("s1")],
                                 clips=[legacy.v2_entry("c1")]))
    client = serve().client
    for category, entry_id in (("episodes", "e1"), ("streams", "s1"),
                               ("clips", "c1")):
        response = client.get(f"/catalog/vault/{category}")
        assert response.status == 200, category
        assert entry_id in response.body, category


# Spec: | v3 | `episodes`, `streams`, `clips` |
def test_v3_valid_categories_all_listed(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")],
                                streams=[catalogs.entry("s1")],
                                clips=[catalogs.entry("c1")]))
    client = serve().client
    for category, entry_id in (("episodes", "e1"), ("streams", "s1"),
                               ("clips", "c1")):
        response = client.get(f"/catalog/vault/{category}")
        assert response.status == 200, category
        assert entry_id in response.body, category


# Spec: | v1 | `entries` |
def test_v1_entries_category_lists_the_flat_entries(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1"),
                                          legacy.v1_entry("e2")]))
    response = serve().client.get("/catalog/vault/entries")
    assert response.status == 200
    assert "e1" in response.body and "e2" in response.body


# Spec: | v1 | `entries` | (a v1 vault has no `episodes` category)
def test_v1_vault_rejects_episodes_category(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    response = serve().client.get("/catalog/vault/episodes")
    assert response.status in REDIRECTS + (400, 404), response.status


# Spec: | v2 | `episodes`, `streams`, `clips` | (a v2 vault has no `entries`)
def test_v2_vault_rejects_entries_category(serve, make_vault, legacy):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    response = serve().client.get("/catalog/vault/entries")
    assert response.status in REDIRECTS + (400, 404), response.status


# ---------------------------------------------------------------------------
# | `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for matching
#   entry |
#
# (A later spec revision replaced the "may reuse the category listing page"
# allowance with a dedicated detail page; the detail page's own content rules
# are exercised in test_viewer_detail.py.)
# ---------------------------------------------------------------------------

# Spec: | `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page ... |
def test_entry_route_returns_html(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault/episodes/e1")
    assert response.status == 200, response.status
    assert "html" in response.headers.get("Content-Type", "").lower()


# Spec: | ... | Entry detail page for matching entry |
# Context: the target entry's title is on the page it lands on.
def test_entry_route_surfaces_the_entry(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault/episodes/e1")
    assert "Title e1" in response.body


# Spec: | ... | Entry *detail* page for matching entry |
# Context: the detail page is a page about that entry, not the listing again.
def test_entry_route_is_a_detail_page(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                          catalogs.entry("e2")]))
    client = serve().client
    listing = client.get("/catalog/vault/episodes").body
    page = client.get("/catalog/vault/episodes/e1").body
    assert page != listing
    assert "Title e1" in page
    assert "Title e2" not in page, page


# Spec: | ... | Entry detail page ... |
# Context: the link produced by `digest` for a v1 vault is a working target.
def test_entry_route_works_for_v1_entries(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    response = serve().client.get("/catalog/vault/entries/e1")
    assert response.status == 200
    assert "Title e1" in response.body


# Spec: | ... | Entry detail page ... | (v2 stream link targets resolve too)
def test_entry_route_works_for_v2_streams(serve, make_vault, legacy):
    make_vault(legacy.v2_catalog(streams=[legacy.v2_entry("s1")]))
    response = serve().client.get("/catalog/vault/streams/s1")
    assert response.status == 200
    assert "Title s1" in response.body


# ---------------------------------------------------------------------------
# | Any HTTP error | Well-formed HTTP response; no raw exception or stack trace
#   exposure |
# ---------------------------------------------------------------------------

# Spec: | Any HTTP error | Well-formed HTTP response; no raw exception ... |
def test_unknown_path_is_well_formed(serve):
    response = serve().client.get("/nope/nothing")
    assert response.status in (200, 302, 303, 400, 404), response.status
    assert response.headers.get("Content-Type")
    assert "Traceback" not in response.body


# Spec: | Any HTTP error | ... no raw exception or stack trace exposure |
def test_broken_catalog_is_not_a_stack_trace(serve, make_vault):
    make_vault(None, raw="{ this is not json")
    response = serve().client.get("/catalog/vault/episodes")
    assert response.status != 500, response.body
    assert "Traceback" not in response.body
    assert 'File "' not in response.body


# Spec: | Any HTTP error | Well-formed HTTP response ... |
# Context: the server stays alive after a bad request.
def test_server_survives_bad_requests(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    client = serve().client
    client.get("/catalog/../../etc/passwd")
    client.get("/catalog/vault/episodes/%2e%2e")
    client.get("/catalog//")
    assert client.get("/").status == 200
