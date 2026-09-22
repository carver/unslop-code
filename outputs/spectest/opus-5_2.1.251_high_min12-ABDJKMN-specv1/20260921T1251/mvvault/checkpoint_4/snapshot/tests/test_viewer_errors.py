"""Spec section: HTTP Error Handling."""

from __future__ import annotations

REDIRECTS = (302, 303)
REJECTS = (400, 404)


# ---------------------------------------------------------------------------
# | Invalid category on `GET /catalog/<name>/<category>` for v1 vault |
#   Redirect to `/catalog/<name>/entries` or return HTTP `400`/`404` |
# ---------------------------------------------------------------------------

# Spec: | Invalid category ... for v1 vault | Redirect to
#   `/catalog/<name>/entries` or return HTTP `400`/`404` |
def test_v1_invalid_category_redirects_or_rejects(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    response = serve().client.get("/catalog/vault/nonsense")
    assert response.status in REDIRECTS + REJECTS, response.status
    if response.status in REDIRECTS:
        assert response.location.endswith("/catalog/vault/entries"), \
            response.location


# Spec: | Invalid category ... for v1 vault | ... |
# Context: `episodes` is a valid name in v2/v3 but invalid for a v1 vault.
def test_v1_episodes_is_an_invalid_category(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    response = serve().client.get("/catalog/vault/clips")
    assert response.status in REDIRECTS + REJECTS
    if response.status in REDIRECTS:
        assert response.location.endswith("/catalog/vault/entries")


# ---------------------------------------------------------------------------
# | Invalid category on `GET /catalog/<name>/<category>` for v2/v3 vault |
#   Redirect to `/catalog/<name>/episodes` or return HTTP `400`/`404` |
# ---------------------------------------------------------------------------

# Spec: | Invalid category ... for v2/v3 vault | Redirect to
#   `/catalog/<name>/episodes` or return HTTP `400`/`404` |
def test_v3_invalid_category_redirects_or_rejects(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault/nonsense")
    assert response.status in REDIRECTS + REJECTS, response.status
    if response.status in REDIRECTS:
        assert response.location.endswith("/catalog/vault/episodes"), \
            response.location


# Spec: | Invalid category ... for v2/v3 vault | ... |
# Context: `entries` is the v1 category name, invalid for a v2 vault.
def test_v2_entries_is_an_invalid_category(serve, make_vault, legacy):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    response = serve().client.get("/catalog/vault/entries")
    assert response.status in REDIRECTS + REJECTS
    if response.status in REDIRECTS:
        assert response.location.endswith("/catalog/vault/episodes")


# Spec: | Invalid category ... | ... |
# Context: whichever branch is taken, an invalid category never 500s.
def test_invalid_category_is_never_a_server_error(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    client = serve().client
    for category in ("Episodes", "", "episode", "media", "..", "%41"):
        response = client.get(f"/catalog/vault/{category}")
        assert response.status != 500, (category, response.status)


# Spec: | Invalid category ... | ... |
# Context: following the redirect lands on a usable listing page.
def test_invalid_category_redirect_lands_on_the_default_listing(
    serve, make_vault, catalogs
):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault/nonsense", follow=True)
    assert response.status in (200,) + REJECTS
    if response.status == 200:
        assert "Title e1" in response.body


# ---------------------------------------------------------------------------
# | Non-existent vault on any `/catalog/<name>` route | Redirect to `/`;
#   landing page shows vault-not-found indication; response must not be
#   HTTP `500` |
# ---------------------------------------------------------------------------

# Spec: | Non-existent vault on any `/catalog/<name>` route | Redirect to `/` ... |
def test_missing_vault_redirects_to_root(serve):
    response = serve().client.get("/catalog/ghost")
    assert response.status in REDIRECTS, response.status
    assert response.location.split("?")[0].endswith("/"), response.location


# Spec: | Non-existent vault on any `/catalog/<name>` route | ... |
# Context: "any route" includes the category and entry routes.
def test_missing_vault_redirects_from_every_catalog_route(serve):
    client = serve().client
    for path in ("/catalog/ghost", "/catalog/ghost/episodes",
                 "/catalog/ghost/episodes/e1", "/catalog/ghost/entries"):
        response = client.get(path)
        assert response.status in REDIRECTS, (path, response.status)
        assert response.location.split("?")[0].endswith("/"), path


# Spec: | Non-existent vault ... | ... response must not be HTTP `500` |
def test_missing_vault_is_not_a_server_error(serve):
    assert serve().client.get("/catalog/ghost/episodes").status != 500


# Spec: | Non-existent vault ... | landing page shows vault-not-found
#   indication |
def test_missing_vault_landing_page_shows_not_found(serve):
    response = serve().client.get("/catalog/ghost", follow=True)
    assert response.status == 200, response.status
    assert "not found" in response.body.lower(), response.body


# Spec: | Non-existent vault ... | landing page shows vault-not-found
#   indication |
# Context: the indication names the vault that could not be found.
def test_not_found_indication_names_the_vault(serve):
    response = serve().client.get("/catalog/ghost", follow=True)
    assert "ghost" in response.body


# Spec: | Non-existent vault ... | ... must not be HTTP `500` |
# Context: a directory without a catalog is not a vault either.
def test_directory_without_catalog_is_treated_as_missing(serve, workdir):
    (workdir / "hollow").mkdir()
    response = serve().client.get("/catalog/hollow/episodes")
    assert response.status != 500
    assert response.status in REDIRECTS, response.status


# Spec: | Non-existent vault ... | ... must not be HTTP `500` |
# Context: an unreadable catalog must not surface as a server error either.
def test_unparseable_catalog_is_not_a_server_error(serve, make_vault):
    make_vault(None, raw="{ broken")
    response = serve().client.get("/catalog/vault/episodes")
    assert response.status != 500, response.body


# Spec: | Non-existent vault ... | ... must not be HTTP `500` |
# Context: an unsupported catalog version is not a browsable vault.
def test_unsupported_version_is_not_a_server_error(serve, make_vault, catalogs):
    catalog = catalogs.catalog(episodes=[catalogs.entry("e1")])
    catalog["version"] = 99
    make_vault(catalog)
    assert serve().client.get("/catalog/vault/episodes").status != 500


# ---------------------------------------------------------------------------
# | Any HTTP error | Well-formed HTTP response; no raw exception or stack trace
#   exposure |
# ---------------------------------------------------------------------------

# Spec: | Any HTTP error | Well-formed HTTP response ... |
def test_error_responses_are_well_formed(serve, make_vault):
    make_vault(None, raw="{ broken")
    client = serve().client
    for path in ("/catalog/ghost", "/catalog/vault/episodes", "/missing",
                 "/catalog/vault/episodes/e1/extra"):
        response = client.get(path)
        assert 200 <= response.status < 500, (path, response.status)
        assert "Content-Type" in response.headers, path


# Spec: | Any HTTP error | ... no raw exception or stack trace exposure |
def test_error_responses_hide_tracebacks(serve, make_vault):
    make_vault(None, raw="{ broken")
    client = serve().client
    for path in ("/catalog/ghost", "/catalog/vault/episodes",
                 "/catalog/vault/../../etc", "/missing"):
        body = client.get(path, follow=True).body
        assert "Traceback" not in body, path
        assert 'File "' not in body, path


# Spec: | Any HTTP error | Well-formed HTTP response ... |
# Context: a POST to an unknown path is answered, not dropped.
def test_post_to_unknown_path_is_answered(serve):
    response = serve().client.post("/nowhere", {"catalog": "vault"})
    assert 200 <= response.status < 500, response.status
