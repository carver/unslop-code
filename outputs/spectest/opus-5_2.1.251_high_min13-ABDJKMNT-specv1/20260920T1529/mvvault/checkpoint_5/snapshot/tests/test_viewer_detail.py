"""Spec sections: the `/catalog/<name>/<category>/<id>` route, its lookup rules,
its page content, and the version-aware source link."""

import pytest
from conftest import (
    V1_KEY,
    V1_OLDER_KEY,
    V2_KEY,
    V2_OLDER_KEY,
    chart_points,
    place_media,
    place_preview,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

REDIRECTS = (302, 303)
SOURCE = "https://example.test/a"


def v3_vault(tmp_path, name="demo", **categories):
    return write_vault(tmp_path, v3_catalog(SOURCE, **categories), name=name)


def refuses_lookup(response, listing):
    """Whether a lookup was refused the way the error table allows."""
    if response.status in REDIRECTS:
        return response.location == listing
    return response.status == 404


# `/catalog/<name>/<category>/<id>` Route: "`GET` |
# `/catalog/<name>/<category>/<id>` | Entry detail page for matching entry".
def test_detail_route_serves_a_page_for_the_matching_entry(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])

    response = viewer.get("/catalog/demo/episodes/e1")

    assert response.status == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "title-e1" in response.body
    assert "title-e2" not in response.body


# Lookup Rules: "Category scope | Lookup occurs only inside named category".
def test_lookup_is_confined_to_the_named_category(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], clips=[v3_entry("c1")])

    response = viewer.get("/catalog/demo/clips/e1")

    assert refuses_lookup(response, "/catalog/demo/clips")


# Lookup Rules: "Cross-category duplicate IDs | Do not satisfy lookup".
def test_duplicate_id_in_another_category_does_not_satisfy_lookup(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("dup")], clips=[v3_entry("dup")])

    response = viewer.get("/catalog/demo/streams/dup")

    assert refuses_lookup(response, "/catalog/demo/streams")


# Lookup Rules: "Cross-category duplicate IDs" — each category answers with its
# own entry, never the other category's entry of the same id.
def test_duplicate_ids_resolve_within_their_own_category(viewer, tmp_path):
    episode = v3_entry("dup", title={V2_KEY: "the episode"})
    clip = v3_entry("dup", title={V2_KEY: "the clip"})
    v3_vault(tmp_path, episodes=[episode], clips=[clip])

    assert "the episode" in viewer.get("/catalog/demo/episodes/dup").body
    assert "the clip" in viewer.get("/catalog/demo/clips/dup").body


# Lookup Rules: "Removed entries (v3) | Remain accessible on detail page".
def test_removed_entries_are_still_reachable(viewer, tmp_path):
    removed = v3_entry("e1", removed={V2_OLDER_KEY: False, V2_KEY: True})
    v3_vault(tmp_path, episodes=[removed])

    response = viewer.get("/catalog/demo/episodes/e1")

    assert response.status == 200
    assert "title-e1" in response.body


# Lookup Rules: "v1 lookup | Lookup in `entries` array when category is
# `entries`".
def test_v1_looks_up_inside_the_entries_array(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1"), v1_entry("e2")]))

    response = viewer.get("/catalog/demo/entries/e2")

    assert response.status == 200
    assert "title-e2" in response.body


# Lookup Rules: "v2/v3 lookup | Lookup in matching category array".
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_looks_up_inside_each_category_array(viewer, tmp_path, category):
    v3_vault(tmp_path, **{category: [v3_entry("x1")]})

    response = viewer.get(f"/catalog/demo/{category}/x1")

    assert response.status == 200
    assert "title-x1" in response.body


@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_looks_up_inside_each_category_array(viewer, tmp_path, category):
    write_vault(tmp_path, v2_catalog(SOURCE, **{category: [v2_entry("x1")]}))

    response = viewer.get(f"/catalog/demo/{category}/x1")

    assert response.status == 200
    assert "title-x1" in response.body


# Page Content: "Current title | Latest value from `title` history, resolved
# per version key format" — v2/v3 keys compare lexicographically.
def test_title_is_the_latest_iso_keyed_value(viewer, tmp_path):
    entry = v3_entry("e1", title={V2_OLDER_KEY: "stale title", V2_KEY: "current title"})
    v3_vault(tmp_path, episodes=[entry])

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "current title" in body
    assert "stale title" not in body


# Page Content: "Current title ... resolved per version key format" — v1 keys
# compare numerically, so `999999999` is an older key than `1718444400`.
def test_v1_title_is_the_latest_epoch_keyed_value(viewer, tmp_path):
    entry = v1_entry("e1", title={"999999999": "stale title", V1_KEY: "current title"})
    write_vault(tmp_path, v1_catalog([entry]))

    body = viewer.get("/catalog/demo/entries/e1").body

    assert "current title" in body
    assert "stale title" not in body


# Page Content: "Current description | Latest value from `description` history,
# resolved per version key format".
def test_description_is_the_latest_iso_keyed_value(viewer, tmp_path):
    entry = v3_entry("e1", description={V2_OLDER_KEY: "stale text", V2_KEY: "current text"})
    v3_vault(tmp_path, episodes=[entry])

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "current text" in body
    assert "stale text" not in body


def test_v1_description_is_the_latest_epoch_keyed_value(viewer, tmp_path):
    entry = v1_entry("e1", description={"999999999": "stale text", V1_KEY: "current text"})
    write_vault(tmp_path, v1_catalog([entry]))

    body = viewer.get("/catalog/demo/entries/e1").body

    assert "current text" in body
    assert "stale text" not in body


# Page Content: "Published date | Displayed".
def test_published_date_is_displayed(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", published="2021-03-04T05:06:07")])

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "2021-03-04T05:06:07" in body


# Page Content: "Dimensions | Display width and height".
def test_dimensions_are_displayed(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", width=640, height=360)])

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "640" in body
    assert "360" in body


# Page Content: "Back navigation | Link to current vault/category listing".
def test_page_links_back_to_the_category_listing(viewer, tmp_path):
    v3_vault(tmp_path, streams=[v3_entry("s1")])

    body = viewer.get("/catalog/demo/streams/s1").body

    assert '"/catalog/demo/streams"' in body


# Page Content: "Media playback reference | Use media static endpoint when
# downloaded media file exists".
def test_downloaded_media_is_referenced_through_the_static_endpoint(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_media(vault, "e1.mp4")

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "/vault/demo/media/e1.mp4" in body


# Page Content: "Downloaded media discovery | A downloaded media file counts as
# matching the entry when a saved filename in `<vault>/media/` contains the
# entry `id`; the detail page uses that exact filename in the media static
# endpoint URL".
def test_media_reference_uses_the_saved_filename(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_media(vault, "clip-e1-1080p.mp4")

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "/vault/demo/media/clip-e1-1080p.mp4" in body


# Page Content: "Downloaded media discovery" — a file for another entry is not
# this entry's media.
def test_media_of_another_entry_is_not_referenced(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])
    place_media(vault, "e2.mp4")

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "/vault/demo/media/" not in body


# Page Content: "Missing downloaded media | Keep metadata and chart data
# visible".
def test_missing_media_keeps_metadata_and_chart_data(viewer, tmp_path):
    entry = v3_entry("e1", views={V2_OLDER_KEY: 10, V2_KEY: 20})
    v3_vault(tmp_path, episodes=[entry])

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "title-e1" in body
    assert "description-e1" in body
    assert "/vault/demo/media/" not in body
    assert chart_points(body, "views") == [(V2_OLDER_KEY, 10), (V2_KEY, 20)]


# Page Content: "Media playback reference" — a saved preview alone is not media
# playback, and the page still renders.
def test_saved_preview_without_media_still_renders(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_preview(vault, "preview-e1.jpg")

    response = viewer.get("/catalog/demo/episodes/e1")

    assert response.status == 200
    assert "/vault/demo/media/" not in response.body


# Detail Page Source Link: "v3 | `<source>/entry/<id>`".
def test_v3_source_link_is_the_source_with_the_entry_path(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert f"{SOURCE}/entry/e1" in body


# Detail Page Source Link: "v2 | `<source>/entry/<id>`".
def test_v2_source_link_is_the_source_with_the_entry_path(viewer, tmp_path):
    write_vault(tmp_path, v2_catalog("https://example.test/b", episodes=[v2_entry("e1")]))

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "https://example.test/b/entry/e1" in body


# Detail Page Source Link: "v1 |
# `https://media.example.com/channel/<source_id>/entry/<id>`".
def test_v1_source_link_is_derived_from_the_source_id(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")], source_id="chan-7"))

    body = viewer.get("/catalog/demo/entries/e1").body

    assert "https://media.example.com/channel/chan-7/entry/e1" in body


# Determinism: "Source link | Version-aware derivation; deterministic for same
# vault and entry".
def test_source_link_is_the_same_on_every_request(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1", key=V1_OLDER_KEY)]))

    first = viewer.get("/catalog/demo/entries/e1").body
    second = viewer.get("/catalog/demo/entries/e1").body

    assert first == second
