"""Spec: the HTTP Error Handling table."""
import pytest

from digest_helpers import v1, v1_entry, v2, v3, v3_entry, legacy_entry


def assert_clean(response):
    """No raw exception or stack trace escapes into the response."""
    assert response.status != 500, response
    lowered = response.body.lower()
    for needle in ("traceback (most recent call last)", "  file \"",
                   "stack trace"):
        assert needle not in lowered, response.body


# Spec: "| Invalid category on `GET /catalog/<name>/<category>` for v1 vault |
# Redirect to `/catalog/<name>/entries` or return HTTP `400`/`404` |"
def test_invalid_category_on_v1_vault(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    response = serve().get("/catalog/vault/bogus")
    assert response.status in (302, 303, 400, 404), response
    if response.is_redirect:
        assert response.location == "/catalog/vault/entries"
    assert_clean(response)


# Spec: "| Invalid category ... for v2/v3 vault | Redirect to
# `/catalog/<name>/episodes` or return HTTP `400`/`404` |"
@pytest.mark.parametrize("builder", [v2, v3])
def test_invalid_category_on_v2_and_v3_vaults(serve, make_vault, builder):
    make_vault(builder())
    response = serve().get("/catalog/vault/bogus")
    assert response.status in (302, 303, 400, 404), response
    if response.is_redirect:
        assert response.location == "/catalog/vault/episodes"
    assert_clean(response)


# Spec: "| Invalid category ... |" -- an invalid category with an id appended
# is handled the same way rather than blowing up.
def test_invalid_category_with_entry_id(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get("/catalog/vault/bogus/e1")
    assert response.status in (200, 302, 303, 400, 404), response
    assert_clean(response)


# Spec: "| Non-existent vault on any `/catalog/<name>` route | Redirect to `/`
# ... response must not be HTTP `500` |"
def test_missing_vault_on_catalog_name_route(serve):
    response = serve().get("/catalog/ghost")
    assert response.is_redirect, response
    assert response.location == "/"
    assert_clean(response)


# Spec: "| Non-existent vault on *any* `/catalog/<name>` route | Redirect to
# `/` ... |" -- the category route too.
def test_missing_vault_on_category_route(serve):
    response = serve().get("/catalog/ghost/episodes")
    assert response.is_redirect, response
    assert response.location == "/"
    assert_clean(response)


# Spec: "| Non-existent vault on any `/catalog/<name>` route | ... |" -- and
# the entry route.
def test_missing_vault_on_entry_route(serve):
    response = serve().get("/catalog/ghost/episodes/e1")
    assert response.is_redirect, response
    assert response.location == "/"
    assert_clean(response)


# Spec: "| Non-existent vault ... | ... landing page shows vault-not-found
# indication ... |"
def test_landing_page_shows_vault_not_found(serve):
    response = serve().get("/catalog/ghost", follow=True)
    assert response.status == 200, response
    assert "not found" in response.body.lower(), response.body


# Spec: "| Non-existent vault ... | ... landing page shows vault-not-found
# indication ... |" -- the indication names the vault that was missing.
def test_not_found_indication_names_the_vault(serve):
    response = serve().get("/catalog/ghost-vault", follow=True)
    assert "ghost-vault" in response.body


# Spec: "| Non-existent vault ... | response must not be HTTP `500` |" -- a
# directory without a `catalog.json` is not a vault either.
def test_directory_without_catalog_is_not_a_vault(serve, tmp_path):
    (tmp_path / "empty").mkdir()
    response = serve().get("/catalog/empty")
    assert response.is_redirect, response
    assert response.location == "/"
    assert_clean(response)


# Spec: "| Any HTTP error | Well-formed HTTP response; no raw exception or
# stack trace exposure |" -- an unparseable `catalog.json`.
def test_corrupt_catalog_does_not_crash(serve, make_raw_vault):
    make_raw_vault("{ this is not json")
    response = serve().get("/catalog/vault/episodes", follow=True)
    assert_clean(response)
    assert response.status == 200


# Spec: "| Any HTTP error | Well-formed HTTP response ... |" -- an unsupported
# catalog version.
def test_unsupported_version_does_not_crash(serve, make_vault):
    make_vault({"version": 99, "source": "u", "episodes": [], "streams": [],
                "clips": []})
    response = serve().get("/catalog/vault")
    assert_clean(response)
    assert response.status in (302, 303, 400, 404)


# Spec: "| Any HTTP error | Well-formed HTTP response ... |" -- an unknown
# top-level path.
def test_unknown_path_is_well_formed(serve):
    response = serve().get("/nope")
    assert response.status in (302, 303, 400, 404), response
    assert_clean(response)


# Spec: "| Any HTTP error | Well-formed HTTP response ... |" -- `/catalog`
# with no vault name at all.
def test_catalog_root_without_name(serve):
    for path in ("/catalog", "/catalog/"):
        response = serve().get(path)
        assert response.status in (200, 302, 303, 400, 404), response
        assert_clean(response)


# Spec: "| Any HTTP error | ... no raw exception or stack trace exposure |" --
# a path-traversal attempt is refused cleanly.
def test_path_traversal_is_refused(serve, make_vault):
    make_vault(v3())
    response = serve().get("/catalog/..%2F..%2Fetc/episodes")
    assert_clean(response)
    assert response.status in (302, 303, 400, 404)


# Spec: "| Any HTTP error | Well-formed HTTP response ... |" -- an unsupported
# method on a known route.
def test_unsupported_method_is_well_formed(serve):
    response = serve().request("PUT", "/")
    assert response.status in (400, 404, 405, 501), response
    assert_clean(response)


# Spec: "| Any HTTP error | ... |" -- POSTing to a `/catalog` route.
def test_post_to_catalog_route_is_well_formed(serve, make_vault):
    make_vault(v3())
    response = serve().post("/catalog/vault", fields={"catalog": "vault"})
    assert response.status in (302, 303, 400, 404, 405, 501), response
    assert_clean(response)


# Spec: "| Any HTTP error | ... |" -- a malformed form body on `POST /` falls
# back to the missing-field behaviour rather than erroring.
def test_malformed_post_body(serve):
    response = serve().post("/", raw="%%%not=valid&&&")
    assert response.status in (200, 302, 303, 400), response
    assert_clean(response)


# Spec: "| Any HTTP error | ... |" -- an entry id that is in no category.
def test_unknown_entry_id_does_not_crash(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get("/catalog/vault/episodes/nosuch")
    assert response.status in (200, 302, 303, 400, 404), response
    assert_clean(response)


# Spec: "| Any HTTP error | ... |" -- entries that are not objects at all.
def test_malformed_entries_do_not_crash(serve, make_vault):
    make_vault({"version": 3, "source": "u", "episodes": ["nope", 7, {}],
                "streams": [], "clips": []})
    response = serve().get("/catalog/vault/episodes", follow=True)
    assert_clean(response)


# Spec: "| Any HTTP error | Well-formed HTTP response ... |" -- every response
# carries a status line and headers the client can parse (implied by the raw
# client here succeeding) and the server keeps serving afterwards.
def test_server_survives_bad_requests(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Fine")]))
    server = serve()
    server.get("/catalog/ghost/episodes/e1")
    server.get("/nope")
    server.post("/", raw="&&&")
    assert "Fine" in server.get("/catalog/vault/episodes").body


# --------------------------------------------------------------------------
# Detail-route and static-route errors
# --------------------------------------------------------------------------
# Spec: "| Missing entry in specified category | HTTP `404`, or redirect to
# category listing with error indication |"
def test_missing_entry_in_category(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get("/catalog/vault/episodes/nosuch")
    assert response.status in (302, 303, 404), response
    if response.is_redirect:
        assert response.location.startswith("/catalog/vault/episodes")
    assert_clean(response)


# Spec: "| Missing entry in specified category | ... redirect to category
# listing with error indication |" -- when the redirect form is used, the
# landing place says something went wrong.
def test_missing_entry_redirect_carries_an_error_indication(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    server = serve()
    response = server.get("/catalog/vault/episodes/nosuch")
    if response.is_redirect:
        followed = server.get("/catalog/vault/episodes/nosuch", follow=True)
        assert "not found" in followed.body.lower(), followed.body


# Spec: "| Missing entry in specified category | ... |" -- an id that exists
# only in another category is missing for this one.
def test_entry_from_another_category_is_missing(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")], clips=[v3_entry(id="c1")]))
    response = serve().get("/catalog/vault/episodes/c1")
    assert response.status in (302, 303, 404), response
    assert_clean(response)


# Spec: "| Invalid category on detail route | Same handling allowed for invalid
# category listing route |"
def test_invalid_category_on_detail_route(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    server = serve()
    listing = server.get("/catalog/vault/bogus")
    detail = server.get("/catalog/vault/bogus/e1")
    assert detail.status in (302, 303, 400, 404), detail
    if listing.is_redirect and detail.is_redirect:
        assert detail.location == listing.location
    assert_clean(detail)


# Spec: "| Invalid category on detail route | ... |" -- on a v1 vault the
# v2/v3 category names are the invalid ones.
def test_invalid_category_on_detail_route_for_v1(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    response = serve().get("/catalog/vault/episodes/e1")
    assert response.status in (302, 303, 400, 404), response
    if response.is_redirect:
        assert response.location == "/catalog/vault/entries"
    assert_clean(response)


# Spec: "| Non-existent vault on detail or static route | Redirect to landing
# page with vault-not-found indication |"
def test_missing_vault_on_detail_route(serve):
    response = serve().get("/catalog/ghost/episodes/e1")
    assert response.is_redirect, response
    assert response.location == "/"
    assert_clean(response)


# Spec: "| Non-existent media file | HTTP `404` |" + "| Non-existent preview
# image | HTTP `404` |" -- both are clean pages, not tracebacks.
def test_missing_static_assets_are_clean_404s(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    server = serve()
    for path in ("/vault/vault/media/nope.mp4", "/vault/vault/preview/nope"):
        response = server.get(path)
        assert response.status == 404, response
        assert_clean(response)


# Spec: "| Path traversal attempt | HTTP `403` or HTTP `404` |"
def test_traversal_attempt_status(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get("/vault/vault/media/..%2F..%2Fcatalog.json")
    assert response.status in (403, 404), response
    assert_clean(response)


# Spec: "| Any HTTP error | Well-formed response; no raw stack trace or
# internal detail exposure |" -- no filesystem path of the host leaks out.
def test_errors_do_not_leak_internal_paths(serve, make_vault, tmp_path):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    server = serve()
    for path in ("/vault/vault/media/nope.mp4", "/catalog/vault/episodes/nope",
                 "/vault/vault/media/../catalog.json"):
        response = server.get(path)
        assert str(tmp_path) not in response.body, response.body
        assert_clean(response)


# Spec: "| Any HTTP error | ... |" -- an entry whose tracked fields are not
# history objects still renders a page rather than a traceback.
def test_detail_page_survives_malformed_history(serve, make_vault):
    make_vault({"version": 3, "source": "https://s.example.com",
                "episodes": [{"id": "e1", "published": "2024-05-01T12:00:00",
                              "width": 1, "height": 2, "title": "flat",
                              "views": ["nope"], "likes": None}],
                "streams": [], "clips": []})
    response = serve().get("/catalog/vault/episodes/e1")
    assert response.status in (200, 302, 303, 404), response
    assert_clean(response)
