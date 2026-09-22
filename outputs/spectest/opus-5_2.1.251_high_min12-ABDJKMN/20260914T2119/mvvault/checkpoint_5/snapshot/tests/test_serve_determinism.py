"""Spec: the viewer rows of the Determinism table."""
import pytest

from digest_helpers import v1, v1_entry, v2, v3, v3_entry, section_links
from viewer_helpers import DEFAULT_HOST, DEFAULT_PORT, listed_ids


# Spec: "| Listing order | Matches category-array order in `catalog.json` |" --
# and repeating the request does not reshuffle it.
def test_listing_order_is_stable_across_requests(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id=name) for name in
                            ("d", "a", "c", "b")]))
    server = serve()
    first = server.get("/catalog/vault/episodes").body
    second = server.get("/catalog/vault/episodes").body
    assert listed_ids(first, "vault", "episodes") == ["d", "a", "c", "b"]
    assert first == second


# Spec: "| Default category redirect | Version-dependent |" -- the same vault
# always redirects to the same place.
@pytest.mark.parametrize("catalog,expected", [
    (v1(entries=[v1_entry(id="e1")]), "/catalog/vault/entries"),
    (v2(), "/catalog/vault/episodes"),
    (v3(), "/catalog/vault/episodes"),
])
def test_default_redirect_is_deterministic(serve, make_vault, catalog, expected):
    make_vault(catalog)
    server = serve()
    assert [server.get("/catalog/vault").location for _ in range(3)] == \
        [expected] * 3


# Spec: "| Redirect status | HTTP `302` or `303` |" -- for every redirecting
# route the viewer exposes.
def test_every_redirect_uses_302_or_303(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    server = serve()
    responses = [
        server.get("/catalog/vault"),
        server.get("/catalog/ghost"),
        server.get("/catalog/ghost/episodes"),
        server.post("/", fields={"catalog": "vault"}),
        server.post("/", fields={}),
    ]
    for response in responses:
        assert response.status in (302, 303), response


# Spec: "| Valid categories | Version-dependent: v1 uses `entries`; v2/v3 use
# `episodes`, `streams`, `clips` |"
def test_valid_categories_are_version_dependent(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]), name="one")
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="three")
    server = serve()
    assert server.get("/catalog/one/entries").status == 200
    assert server.get("/catalog/three/episodes").status == 200
    assert server.get("/catalog/one/streams").status in (302, 303, 400, 404)
    assert server.get("/catalog/three/entries").status in (302, 303, 400, 404)


# Spec: "| Default port | `8840` |" + "| Default viewer-link host | `127.0.0.1`
# |" + "| Default viewer-link scheme | `http://` |" -- repeated digests emit
# byte-identical links.
def test_viewer_link_defaults_are_deterministic(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    runs = [section_links(run("digest", "vault").stdout) for _ in range(3)]
    expected = "http://%s:%d/catalog/vault/episodes/e1" % (DEFAULT_HOST,
                                                           DEFAULT_PORT)
    assert all(item["Episodes"]["Added"] == [expected] for item in runs)


# Spec: "| Recent-vault links on `/` | Use the same resolved default-category
# route as `/catalog/<name>` would redirect to |" -- checked for every version.
def test_recent_links_match_redirect_for_every_version(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]), name="one")
    make_vault(v2(), name="two")
    make_vault(v3(), name="three")
    server = serve()
    expected = {}
    for name in ("one", "two", "three"):
        expected[name] = server.get("/catalog/%s" % name).location
    from viewer_helpers import catalog_links
    found = [href for href, _ in catalog_links(server.get("/").body)]
    assert sorted(found) == sorted(expected.values())


# Spec: "| Recent-vault order | Most recently visited first |" -- stable across
# repeated landing-page loads.
def test_recent_order_is_stable(serve, make_vault):
    for name in ("one", "two"):
        make_vault(v3(), name=name)
    server = serve()
    server.get("/catalog/one/episodes")
    server.get("/catalog/two/episodes")
    from viewer_helpers import catalog_links
    first = [href for href, _ in catalog_links(server.get("/").body)]
    second = [href for href, _ in catalog_links(server.get("/").body)]
    assert first == second == ["/catalog/two/episodes", "/catalog/one/episodes"]


# Spec: "| HTTP behavior defined above | Required |" -- the listing page for a
# fixed vault is byte-stable, so nothing wall-clock-derived leaks into it.
def test_listing_page_is_byte_stable(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Stable")]))
    server = serve()
    assert server.get("/catalog/vault/episodes").body == \
        server.get("/catalog/vault/episodes").body


# --------------------------------------------------------------------------
# Detail page / chart determinism
# --------------------------------------------------------------------------
# Spec: "| HTTP behavior defined above | Required |" -- the detail page for a
# fixed vault is byte-stable too.
def test_detail_page_is_byte_stable(serve, make_vault):
    from digest_helpers import K1, K2
    make_vault(v3(episodes=[v3_entry(id="e1", title="Stable",
                                     views={K1: 10, K2: 20})]))
    server = serve()
    assert server.get("/catalog/vault/episodes/e1").body == \
        server.get("/catalog/vault/episodes/e1").body


# Spec: "| Current tracked value (v1) | Value at latest key by numeric
# comparison |" -- "999999999" is older than "1000000000".
def test_v1_current_value_uses_numeric_comparison(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1",
                                    title={"1000000000": "Newer",
                                           "999999999": "Older"})]))
    body = serve().get("/catalog/vault/entries/e1").body
    assert "Newer" in body
    assert "Older" not in body


# Spec: "| Current tracked value (v2/v3) | Value at latest key by lexicographic
# comparison |"
def test_v3_current_value_uses_lexicographic_comparison(serve, make_vault):
    from digest_helpers import K1, K3
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     title={K3: "Newer", K1: "Older"})]))
    body = serve().get("/catalog/vault/episodes/e1").body
    assert "Newer" in body
    assert "Older" not in body


# Spec: "| Downloaded media reference | When rendered, the detail page uses the
# matched saved filename in `/vault/<name>/media/<file>` |" -- the same match
# on every request.
def test_media_reference_is_deterministic(serve, make_vault, save_asset):
    from viewer_helpers import vault_refs
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("media", "e1.mp4")
    server = serve()
    refs = [vault_refs(server.get("/catalog/vault/episodes/e1").body)
            for _ in range(3)]
    assert refs[0] == refs[1] == refs[2]
    assert "/vault/vault/media/e1.mp4" in refs[0]


# Spec: "| Chart output timestamps | Always ISO 8601 regardless of vault
# version |" -- v1 and v3 vaults holding the same instants agree.
def test_chart_timestamps_agree_across_versions(serve, make_vault):
    from digest_helpers import E1, E2, K1, K2
    from viewer_helpers import chart_timestamps
    make_vault(v1(entries=[v1_entry(id="e1", views={E1: 1, E2: 2})]), name="a")
    make_vault(v3(episodes=[v3_entry(id="e1", views={K1: 1, K2: 2})]), name="b")
    server = serve()
    assert chart_timestamps(server.get("/catalog/a/entries/e1").body,
                            "views") == [K1, K2]
    assert chart_timestamps(server.get("/catalog/b/episodes/e1").body,
                            "views") == [K1, K2]
