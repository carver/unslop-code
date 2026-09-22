"""Spec section: `/catalog/<name>/<category>/<id>` route, lookup and content."""

from __future__ import annotations

import urllib.parse

REDIRECTS = (301, 302, 303, 307, 308)


def assert_missing_entry(client, path, name, category):
    """| Missing entry in specified category | HTTP `404`, or redirect to
    category listing with error indication |
    """
    response = client.get(path)
    if response.status == 404:
        assert "html" in response.headers.get("Content-Type", "").lower()
        return response
    assert response.status in REDIRECTS, response.status
    target = urllib.parse.urlsplit(response.location or "")
    assert target.path == f"/catalog/{name}/{category}", response.location
    landed = client.get(path, follow=True)
    plain = client.get(f"/catalog/{name}/{category}")
    assert landed.body != plain.body, \
        "redirect to the listing carries no error indication"
    return response


# ---------------------------------------------------------------------------
# | `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for matching
#   entry |
# ---------------------------------------------------------------------------

# Spec: | `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page ... |
def test_detail_route_is_ok(serve, make_vault, catalogs, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get(detail.path("vault", "episodes", "e1"))
    assert response.status == 200, response.status


# Spec: | ... | Entry detail page for matching entry |
# Context: the detail page is HTML, like the rest of the viewer.
def test_detail_route_serves_html(serve, make_vault, catalogs, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get(detail.path("vault", "episodes", "e1"))
    assert "html" in response.headers.get("Content-Type", "").lower()
    assert response.body.lstrip().lower().startswith("<!doctype html")


# Spec: | ... | Entry *detail* page for matching entry |
# Context: a detail page is about one entry, so a sibling entry of the same
# category is not rendered as another item of the page.
def test_detail_page_is_not_the_category_listing(serve, make_vault, catalogs,
                                                 detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                          catalogs.entry("e2")]))
    client = serve().client
    page = client.get(detail.path("vault", "episodes", "e1")).body
    assert "Title e1" in page
    assert "Title e2" not in page, page
    assert page != client.get("/catalog/vault/episodes").body


# ---------------------------------------------------------------------------
# | Category scope | Lookup occurs only inside named category |
# ---------------------------------------------------------------------------

# Spec: | Category scope | Lookup occurs only inside named category |
def test_lookup_finds_an_entry_of_the_named_category(serve, make_vault,
                                                     catalogs, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")],
                                streams=[catalogs.entry("s1")],
                                clips=[catalogs.entry("c1")]))
    client = serve().client
    for category, entry_id in (("episodes", "e1"), ("streams", "s1"),
                               ("clips", "c1")):
        response = client.get(detail.path("vault", category, entry_id))
        assert response.status == 200, (category, response.status)
        assert f"Title {entry_id}" in response.body


# Spec: | Category scope | Lookup occurs only inside named category |
# Context: an id that lives in another category is not found here.
def test_lookup_does_not_reach_into_another_category(serve, make_vault,
                                                     catalogs, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")],
                                clips=[catalogs.entry("c1")]))
    client = serve().client
    assert_missing_entry(client, detail.path("vault", "episodes", "c1"),
                         "vault", "episodes")


# ---------------------------------------------------------------------------
# | Cross-category duplicate IDs | Do not satisfy lookup |
# ---------------------------------------------------------------------------

# Spec: | Cross-category duplicate IDs | Do not satisfy lookup |
# Context: the same id in `clips` must not answer an `episodes` request.
def test_cross_category_duplicate_id_does_not_satisfy_lookup(
        serve, make_vault, catalogs, detail):
    make_vault(catalogs.catalog(
        episodes=[catalogs.entry("only-episode")],
        clips=[catalogs.entry("dup")],
    ))
    client = serve().client
    assert client.get(detail.path("vault", "clips", "dup")).status == 200
    assert_missing_entry(client, detail.path("vault", "episodes", "dup"),
                         "vault", "episodes")


# Spec: | Cross-category duplicate IDs | Do not satisfy lookup |
# Context: when both categories hold the id, each page shows its own copy.
def test_duplicate_id_in_two_categories_resolves_per_category(
        serve, make_vault, catalogs, detail):
    episode = catalogs.entry("dup")
    episode["title"] = {catalogs.STAMP_1: "Episode copy"}
    clip = catalogs.entry("dup")
    clip["title"] = {catalogs.STAMP_1: "Clip copy"}
    make_vault(catalogs.catalog(episodes=[episode], clips=[clip]))
    client = serve().client

    episode_page = client.get(detail.path("vault", "episodes", "dup")).body
    clip_page = client.get(detail.path("vault", "clips", "dup")).body
    assert "Episode copy" in episode_page and "Clip copy" not in episode_page
    assert "Clip copy" in clip_page and "Episode copy" not in clip_page


# ---------------------------------------------------------------------------
# | Removed entries (v3) | Remain accessible on detail page |
# ---------------------------------------------------------------------------

# Spec: | Removed entries (v3) | Remain accessible on detail page |
def test_removed_entry_detail_page_is_reachable(serve, make_vault, catalogs,
                                                detail):
    entry = catalogs.entry("gone")
    entry["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    response = serve().client.get(detail.path("vault", "episodes", "gone"))
    assert response.status == 200, response.status
    assert "Title gone" in response.body


# Spec: | Removed entries (v3) | Remain accessible on detail page |
# Context: a removed entry keeps its metadata and its chart data.
def test_removed_entry_keeps_metadata_and_charts(serve, make_vault, catalogs,
                                                 detail):
    entry = catalogs.entry("gone")
    entry["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    entry["views"] = {catalogs.STAMP_1: 10, catalogs.STAMP_2: 20}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "gone")).body
    assert "1920" in page and "1080" in page
    assert detail.values(page, "views") == [10, 20]


# ---------------------------------------------------------------------------
# | v1 lookup | Lookup in `entries` array when category is `entries` |
# ---------------------------------------------------------------------------

# Spec: | v1 lookup | Lookup in `entries` array when category is `entries` |
def test_v1_detail_page_resolves_from_the_entries_array(serve, make_vault,
                                                        legacy, detail):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1"),
                                          legacy.v1_entry("e2")]))
    response = serve().client.get(detail.path("vault", "entries", "e1"))
    assert response.status == 200, response.status
    assert "Title e1" in response.body
    assert "Title e2" not in response.body


# Spec: | v1 lookup | Lookup in `entries` array ... |
# Context: an id the flat array does not hold is missing.
def test_v1_detail_page_rejects_an_unknown_id(serve, make_vault, legacy, detail):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert_missing_entry(serve().client, detail.path("vault", "entries", "nope"),
                         "vault", "entries")


# ---------------------------------------------------------------------------
# | v2/v3 lookup | Lookup in matching category array |
# ---------------------------------------------------------------------------

# Spec: | v2/v3 lookup | Lookup in matching category array |
def test_v2_detail_page_resolves_per_category(serve, make_vault, legacy, detail):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")],
                                 streams=[legacy.v2_entry("s1")],
                                 clips=[legacy.v2_entry("c1")]))
    client = serve().client
    for category, entry_id in (("episodes", "e1"), ("streams", "s1"),
                               ("clips", "c1")):
        response = client.get(detail.path("vault", category, entry_id))
        assert response.status == 200, (category, response.status)
        assert f"Title {entry_id}" in response.body


# Spec: | v2/v3 lookup | Lookup in matching category array |
# Context: v2 cross-category lookup fails the same way v3's does.
def test_v2_cross_category_lookup_fails(serve, make_vault, legacy, detail):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")],
                                 streams=[legacy.v2_entry("s1")]))
    assert_missing_entry(serve().client, detail.path("vault", "episodes", "s1"),
                         "vault", "episodes")


# ---------------------------------------------------------------------------
# | Current title | Latest value from `title` history, resolved per version
#   key format |
# | Current description | Latest value from `description` history, resolved per
#   version key format |
# ---------------------------------------------------------------------------

# Spec: | Current title | Latest value from `title` history ... |
def test_current_title_is_the_latest_v3_value(serve, make_vault, catalogs,
                                              detail):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "First title",
                      catalogs.STAMP_3: "Newest title",
                      catalogs.STAMP_2: "Middle title"}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert "Newest title" in page
    assert "First title" not in page
    assert "Middle title" not in page


# Spec: | Current description | Latest value from `description` history ... |
def test_current_description_is_the_latest_v3_value(serve, make_vault,
                                                    catalogs, detail):
    entry = catalogs.entry("e1")
    entry["description"] = {catalogs.STAMP_1: "Old body",
                            catalogs.STAMP_2: "Current body"}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert "Current body" in page
    assert "Old body" not in page


# Spec: | Current title | ... resolved per version key format |
# Context: v1 keys are UNIX epoch strings, so the latest key is the numerically
# largest one - `"900000000"` sorts after `"1718444400"` as text but is older.
def test_v1_current_title_uses_numeric_key_order(serve, make_vault, legacy,
                                                 detail):
    entry = legacy.v1_entry("e1")
    entry["title"] = {"900000000": "Ancient title",
                      legacy.V1_EPOCH: "Recent title"}
    entry["description"] = {"900000000": "Ancient body",
                            legacy.V1_EPOCH: "Recent body"}
    make_vault(legacy.v1_catalog(entries=[entry]))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert "Recent title" in page and "Ancient title" not in page
    assert "Recent body" in page and "Ancient body" not in page


# Spec: | Current title | ... resolved per version key format |
# Context: v2 keys are ISO 8601 strings, compared lexicographically.
def test_v2_current_title_uses_lexicographic_key_order(serve, make_vault,
                                                       legacy, detail):
    entry = legacy.v2_entry("e1")
    entry["title"] = {"2024-06-15T09:40:00": "Older title",
                      "2024-07-01T00:00:00": "Newer title"}
    make_vault(legacy.v2_catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert "Newer title" in page and "Older title" not in page


# ---------------------------------------------------------------------------
# | Published date | Displayed |
# | Dimensions | Display width and height |
# ---------------------------------------------------------------------------

# Spec: | Published date | Displayed |
def test_published_date_is_displayed(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["published"] = "2023-11-02T07:15:00"
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert "2023-11-02T07:15:00" in page


# Spec: | Dimensions | Display width and height |
def test_dimensions_are_displayed(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["width"] = 3840
    entry["height"] = 2160
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert "3840" in page, page
    assert "2160" in page, page


# Spec: | Published date | Displayed | | Dimensions | ... |
# Context: v1 entries carry the same static fields.
def test_v1_published_and_dimensions_are_displayed(serve, make_vault, legacy,
                                                   detail):
    entry = legacy.v1_entry("e1")
    entry["published"] = "2022-01-09T11:00:00"
    entry["width"] = 640
    entry["height"] = 480
    make_vault(legacy.v1_catalog(entries=[entry]))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert "2022-01-09T11:00:00" in page
    assert "640" in page and "480" in page


# ---------------------------------------------------------------------------
# | Back navigation | Link to current vault/category listing |
# ---------------------------------------------------------------------------

# Spec: | Back navigation | Link to current vault/category listing |
def test_detail_page_links_back_to_the_category_listing(serve, make_vault,
                                                        catalogs, detail):
    make_vault(catalogs.catalog(streams=[catalogs.entry("s1")]))
    page = serve().client.get(detail.path("vault", "streams", "s1")).body
    assert 'href="/catalog/vault/streams"' in page, page


# Spec: | Back navigation | Link to current vault/category listing |
# Context: the back link actually resolves to that listing.
def test_back_link_resolves_to_the_listing(serve, make_vault, catalogs, detail):
    make_vault(catalogs.catalog(streams=[catalogs.entry("s1"),
                                         catalogs.entry("s2")]))
    client = serve().client
    client.get(detail.path("vault", "streams", "s1"))
    listing = client.get("/catalog/vault/streams")
    assert listing.status == 200
    assert "Title s1" in listing.body and "Title s2" in listing.body


# Spec: | Back navigation | Link to current vault/category listing |
# Context: v1's listing lives under the `entries` category.
def test_v1_back_link_points_at_entries(serve, make_vault, legacy, detail):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert 'href="/catalog/vault/entries"' in page, page


# ---------------------------------------------------------------------------
# | Source-platform link | Deterministic URL derived from vault source
#   information and entry `id` |
# | v1 | `https://media.example.com/channel/<source_id>/entry/<id>` |
# | v2 | `<source>/entry/<id>` |
# | v3 | `<source>/entry/<id>` |
# ---------------------------------------------------------------------------

# Spec: | v1 | `https://media.example.com/channel/<source_id>/entry/<id>` |
def test_v1_source_link(serve, make_vault, legacy, detail):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")],
                                 source_id="chan-1"))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert "https://media.example.com/channel/chan-1/entry/e1" in page, page


# Spec: | v1 | `https://media.example.com/channel/<source_id>/entry/<id>` |
# Context: the `source_id` of the vault is what the link carries.
def test_v1_source_link_uses_the_catalog_source_id(serve, make_vault, legacy,
                                                   detail):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("zz")],
                                 source_id="other-channel"))
    page = serve().client.get(detail.path("vault", "entries", "zz")).body
    assert "https://media.example.com/channel/other-channel/entry/zz" in page


# Spec: | v2 | `<source>/entry/<id>` |
def test_v2_source_link(serve, make_vault, legacy, source, detail):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert f"{source.url}/entry/e1" in page, page


# Spec: | v3 | `<source>/entry/<id>` |
def test_v3_source_link(serve, make_vault, catalogs, source, detail):
    make_vault(catalogs.catalog(clips=[catalogs.entry("c9")]))
    page = serve().client.get(detail.path("vault", "clips", "c9")).body
    assert f"{source.url}/entry/c9" in page, page


# Spec: | Source-platform link | Deterministic URL ... |
# Context: the same vault and entry always render the same link.
def test_source_link_is_deterministic(serve, make_vault, catalogs, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    client = serve().client
    path = detail.path("vault", "episodes", "e1")
    first = client.get(path).body
    second = client.get(path).body
    assert first == second


# Spec: | Source-platform link | Deterministic URL ... |
# Context: the link is an actual anchor target, not just loose text.
def test_source_link_is_an_anchor(serve, make_vault, catalogs, source, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert f'href="{source.url}/entry/e1"' in page, page


# ---------------------------------------------------------------------------
# | Media playback reference | Use media static endpoint when downloaded media
#   file exists |
# | Downloaded media discovery | A downloaded media file counts as matching the
#   entry when a saved filename in `<vault>/media/` contains the entry `id`;
#   the detail page uses that exact filename in the media static endpoint URL |
# ---------------------------------------------------------------------------

# Spec: | Media playback reference | Use media static endpoint when downloaded
#   media file exists |
def test_detail_page_references_the_media_endpoint(serve, make_vault, catalogs,
                                                   detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.media_url("vault", "e1.mp4") in page, page


# Spec: | Downloaded media discovery | ... a saved filename ... contains the
#   entry `id`; the detail page uses that exact filename ... |
def test_media_url_uses_the_exact_saved_filename(serve, make_vault, catalogs,
                                                 detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "prefix-e1-suffix.webm")
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.media_url("vault", "prefix-e1-suffix.webm") in page, page


# Spec: | Downloaded media discovery | ... a saved filename in `<vault>/media/`
#   contains the entry `id` ... |
# Context: a file for a different entry is not this entry's media.
def test_media_of_another_entry_is_not_referenced(serve, make_vault, catalogs,
                                                  detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                                  catalogs.entry("other")]))
    detail.write_media(vault, "other.mp4")
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert "other.mp4" not in page, page


# Spec: | Media playback reference | Use media static endpoint ... |
# Context: the referenced URL is one the viewer actually serves.
def test_referenced_media_url_is_servable(serve, make_vault, catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4", b"movie-bytes")
    client = serve().client
    page = client.get(detail.path("vault", "episodes", "e1")).body
    url = detail.media_url("vault", "e1.mp4")
    assert url in page
    response = client.get(url)
    assert response.status == 200, response.status


# ---------------------------------------------------------------------------
# | Missing downloaded media | Keep metadata and chart data visible |
# ---------------------------------------------------------------------------

# Spec: | Missing downloaded media | Keep metadata and chart data visible |
def test_missing_media_keeps_metadata_visible(serve, make_vault, catalogs,
                                              detail):
    entry = catalogs.entry("e1")
    entry["published"] = "2024-02-02T02:02:02"
    make_vault(catalogs.catalog(episodes=[entry]))
    response = serve().client.get(detail.path("vault", "episodes", "e1"))
    assert response.status == 200, response.status
    assert "Title e1" in response.body
    assert "Description e1" in response.body
    assert "2024-02-02T02:02:02" in response.body
    assert "1920" in response.body and "1080" in response.body


# Spec: | Missing downloaded media | Keep metadata and chart data visible |
def test_missing_media_keeps_chart_data_visible(serve, make_vault, catalogs,
                                                detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 2}
    entry["likes"] = {catalogs.STAMP_1: 3, catalogs.STAMP_2: 4}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.values(page, "views") == [1, 2]
    assert detail.values(page, "likes") == [3, 4]


# Spec: | Missing downloaded media | Keep metadata and chart data visible |
# Context: a vault with no `media/` directory at all still renders.
def test_detail_page_without_a_media_directory(serve, make_vault, catalogs,
                                               source, detail):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get(detail.path("vault", "episodes", "e1"))
    assert response.status == 200, response.status
    assert f"{source.url}/entry/e1" in response.body
