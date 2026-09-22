"""Spec: the `/catalog/<name>/<category>/<id>` route, lookup rules and page
content tables, plus the version-aware source link."""
import pytest

from digest_helpers import (E1, E2, K1, K2, legacy_entry, v1, v1_entry, v2, v3,
                            v3_entry)
from viewer_helpers import chart_points, hrefs, text_of, vault_refs


def detail(server, name="vault", category="episodes", entry_id="e1"):
    return server.get("/catalog/%s/%s/%s" % (name, category, entry_id))


# --------------------------------------------------------------------------
# Route table
# --------------------------------------------------------------------------
# Spec: "| `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for
# matching entry |"
def test_detail_route_returns_an_html_page(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Target")]))
    response = detail(serve())
    assert response.status == 200, response
    assert "<html" in response.body.lower()
    assert "Target" in response.body


# Spec: "| ... | Entry detail page for matching entry |" -- a detail page, not
# the category listing: the other entries of the category are not listed.
def test_detail_page_is_not_the_category_listing(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="One"),
                            v3_entry(id="e2", title="Two")]))
    body = detail(serve(), entry_id="e1").body
    assert "One" in body
    assert "Two" not in body


# --------------------------------------------------------------------------
# Lookup rules
# --------------------------------------------------------------------------
# Spec: "| Category scope | Lookup occurs only inside named category |"
def test_lookup_is_scoped_to_the_named_category(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")], clips=[v3_entry(id="c9")]))
    response = detail(serve(), category="episodes", entry_id="c9")
    assert response.status in (302, 303, 404), response


# Spec: "| Cross-category duplicate IDs | Do not satisfy lookup |" -- the same
# id in another category is not served under this one...
def test_duplicate_id_in_another_category_does_not_satisfy_lookup(serve,
                                                                  make_vault):
    make_vault(v3(episodes=[v3_entry(id="dup", title="Episode copy")],
                  clips=[v3_entry(id="dup", title="Clip copy")]))
    server = serve()
    assert "Episode copy" in detail(server, category="episodes",
                                    entry_id="dup").body
    assert "Clip copy" in detail(server, category="clips", entry_id="dup").body


# Spec: "| Cross-category duplicate IDs | Do not satisfy lookup |" -- ...and a
# category that does not hold the id never borrows the duplicate.
def test_duplicate_id_is_not_borrowed_from_another_category(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="dup", title="Episode copy")],
                  clips=[v3_entry(id="dup", title="Clip copy")]))
    body = detail(serve(), category="streams", entry_id="dup")
    assert body.status in (302, 303, 404), body


# Spec: "| Removed entries (v3) | Remain accessible on detail page |"
def test_removed_entry_detail_page_is_served(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="gone", title="Gone Away",
                                     removed={K1: False, K2: True})]))
    response = detail(serve(), entry_id="gone")
    assert response.status == 200, response
    assert "Gone Away" in response.body


# Spec: "| v1 lookup | Lookup in `entries` array when category is `entries` |"
def test_v1_lookup_uses_the_entries_array(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title="Flat One")]))
    response = serve().get("/catalog/vault/entries/e1")
    assert response.status == 200, response
    assert "Flat One" in response.body


# Spec: "| v2/v3 lookup | Lookup in matching category array |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_lookup_uses_the_matching_category_array(serve, make_vault,
                                                    category):
    make_vault(v2(**{category: [legacy_entry(id="x1", title="Named")]}))
    response = detail(serve(), category=category, entry_id="x1")
    assert response.status == 200, response
    assert "Named" in response.body


@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_lookup_uses_the_matching_category_array(serve, make_vault,
                                                    category):
    make_vault(v3(**{category: [v3_entry(id="x1", title="Named")]}))
    response = detail(serve(), category=category, entry_id="x1")
    assert response.status == 200, response
    assert "Named" in response.body


# --------------------------------------------------------------------------
# Page content
# --------------------------------------------------------------------------
# Spec: "| Current title | Latest value from `title` history, resolved per
# version key format |"
def test_current_title_is_the_latest_v3_history_value(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     title={K1: "Old Title",
                                            K2: "New Title"})]))
    body = detail(serve()).body
    assert "New Title" in body
    assert "Old Title" not in body


# Spec: "| Current title | ... resolved per version key format |" -- v1 keys
# are UNIX-epoch strings and resolve numerically.
def test_current_title_for_v1_uses_epoch_key_order(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1",
                                    title={E2: "New Title", E1: "Old Title"})]))
    body = serve().get("/catalog/vault/entries/e1").body
    assert "New Title" in body
    assert "Old Title" not in body


# Spec: "| Current description | Latest value from `description` history,
# resolved per version key format |"
def test_current_description_is_the_latest_history_value(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     description={K1: "Stale blurb",
                                                  K2: "Fresh blurb"})]))
    body = detail(serve()).body
    assert "Fresh blurb" in body
    assert "Stale blurb" not in body


def test_current_description_for_v1_uses_epoch_key_order(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1",
                                    description={E2: "Fresh blurb",
                                                 E1: "Stale blurb"})]))
    body = serve().get("/catalog/vault/entries/e1").body
    assert "Fresh blurb" in body
    assert "Stale blurb" not in body


# Spec: "| Published date | Displayed |"
def test_published_date_is_displayed(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     published="2024-05-01T12:00:00")]))
    assert "2024-05-01" in text_of(detail(serve()).body)


# Spec: "| Dimensions | Display width and height |"
def test_width_and_height_are_displayed(serve, make_vault):
    entry = v3_entry(id="e1")
    entry["width"] = 1280
    entry["height"] = 720
    make_vault(v3(episodes=[entry]))
    text = text_of(detail(serve()).body)
    assert "1280" in text
    assert "720" in text


# Spec: "| Back navigation | Link to current vault/category listing |"
def test_back_navigation_links_to_the_category_listing(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")], clips=[v3_entry(id="c1")]))
    server = serve()
    assert "/catalog/vault/episodes" in hrefs(detail(server).body)
    assert "/catalog/vault/clips" in hrefs(
        detail(server, category="clips", entry_id="c1").body)


# Spec: "| Back navigation | Link to current vault/category listing |" -- the
# link actually reaches the listing.
def test_back_navigation_link_is_followable(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="One"),
                            v3_entry(id="e2", title="Two")]))
    server = serve()
    back = [href for href in hrefs(detail(server).body)
            if href.rstrip("/").endswith("/catalog/vault/episodes")]
    assert back, detail(server).body
    listing = server.get(back[0], follow=True)
    assert listing.status == 200, listing
    assert "One" in listing.body and "Two" in listing.body


# Spec: "| v1 lookup | ... |" -- back navigation on a v1 vault points at
# `entries`, the category that is current for that version.
def test_back_navigation_for_v1_points_at_entries(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    body = serve().get("/catalog/vault/entries/e1").body
    assert "/catalog/vault/entries" in hrefs(body)


# --------------------------------------------------------------------------
# Source link
# --------------------------------------------------------------------------
# Spec: "| v1 | `https://media.example.com/channel/<source_id>/entry/<id>` |"
def test_v1_source_link(serve, make_vault):
    make_vault(v1(source_id="chan42", entries=[v1_entry(id="e1")]))
    body = serve().get("/catalog/vault/entries/e1").body
    assert "https://media.example.com/channel/chan42/entry/e1" in hrefs(body)


# Spec: "| v2 | `<source>/entry/<id>` |"
def test_v2_source_link(serve, make_vault):
    make_vault(v2(source="https://media.example.com/channel/zz",
                  episodes=[legacy_entry(id="e1")]))
    body = detail(serve()).body
    assert "https://media.example.com/channel/zz/entry/e1" in hrefs(body)


# Spec: "| v3 | `<source>/entry/<id>` |"
def test_v3_source_link(serve, make_vault):
    make_vault(v3(source="https://media.example.com/channel/zz",
                  episodes=[v3_entry(id="e1")]))
    body = detail(serve()).body
    assert "https://media.example.com/channel/zz/entry/e1" in hrefs(body)


# Spec: "| Source-platform link | Deterministic URL derived from vault source
# information and entry `id` |" -- the entry id is what varies.
def test_source_link_varies_with_the_entry_id(serve, make_vault):
    make_vault(v3(source="https://media.example.com/channel/zz",
                  episodes=[v3_entry(id="a1"), v3_entry(id="b2")]))
    server = serve()
    for entry_id in ("a1", "b2"):
        body = detail(server, entry_id=entry_id).body
        assert ("https://media.example.com/channel/zz/entry/%s" % entry_id) \
            in hrefs(body)


# Spec: "| Source link | Version-aware derivation; deterministic for same vault
# and entry |"
def test_source_link_is_deterministic(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    server = serve()
    first, second = detail(server).body, detail(server).body
    assert first == second


# --------------------------------------------------------------------------
# Media playback reference
# --------------------------------------------------------------------------
# Spec: "| Media playback reference | Use media static endpoint when downloaded
# media file exists |"
def test_media_reference_uses_the_static_endpoint(serve, make_vault,
                                                  save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("media", "e1.mp4")
    refs = vault_refs(detail(serve()).body)
    assert "/vault/vault/media/e1.mp4" in refs


# Spec: "| Downloaded media discovery | A downloaded media file counts as
# matching the entry when a saved filename in `<vault>/media/` contains the
# entry `id`; the detail page uses that exact filename ... |"
def test_media_discovery_matches_a_filename_containing_the_id(serve,
                                                              make_vault,
                                                              save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("media", "archive-e1-final.webm")
    refs = vault_refs(detail(serve()).body)
    assert "/vault/vault/media/archive-e1-final.webm" in refs


# Spec: "| Downloaded media reference | When rendered, the detail page uses the
# matched saved filename in `/vault/<name>/media/<file>` |" -- and that URL
# actually serves the bytes.
def test_media_reference_is_fetchable(serve, make_vault, save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("media", "e1.mp4", body=b"MEDIABYTES")
    server = serve()
    refs = [ref for ref in vault_refs(detail(server).body)
            if "/media/" in ref]
    assert refs
    assert server.get(refs[0]).body == "MEDIABYTES"


# Spec: "| Missing downloaded media | Keep metadata and chart data visible |"
def test_missing_media_keeps_metadata_and_chart_data(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="No Media",
                                     views={K1: 10, K2: 20})]))
    response = detail(serve())
    assert response.status == 200, response
    text = text_of(response.body)
    assert "No Media" in text
    assert "2024-05-01" in text
    assert chart_points(response.body, "views") is not None


# Spec: "| Missing downloaded media | ... |" -- no media endpoint is referenced
# when nothing in `<vault>/media/` matches the entry.
def test_missing_media_does_not_reference_the_media_endpoint(serve, make_vault,
                                                             save_asset):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    save_asset("media", "other.mp4")
    refs = [ref for ref in vault_refs(detail(serve()).body) if "/media/" in ref]
    assert refs == []
