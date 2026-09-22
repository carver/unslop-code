"""Spec sections: `/catalog/<name>/<category>/<id>` Route, Lookup Rules, and
Page Content."""

from conftest import (
    V1_EPOCH,
    V2_LATER,
    V2_STAMP,
    add_media,
    chart_points,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)


# Spec: `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for
# matching entry
def test_detail_page_is_html_for_a_matching_entry(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/episodes/e1")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "Title e1" in response.text


# Spec: Category scope | Lookup occurs only inside named category
def test_lookup_stays_inside_the_named_category(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")], clips=[v3_entry("c1")]))
    assert serve().get("/catalog/vault/episodes/c1").status_code in (302, 303, 404)


# Spec: Cross-category duplicate IDs | Do not satisfy lookup
def test_duplicate_id_in_another_category_does_not_satisfy_lookup(serve, tmp_path):
    shared = v3_entry("dup", title={V2_STAMP: "Clip title"})
    write_vault(tmp_path, v3_catalog(clips=[shared]))
    assert serve().get("/catalog/vault/episodes/dup").status_code in (302, 303, 404)


# Spec: Cross-category duplicate IDs | ... each category answers with its own entry
def test_the_same_id_in_two_categories_serves_each_category_its_own_entry(serve, tmp_path):
    write_vault(
        tmp_path,
        v3_catalog(
            episodes=[v3_entry("dup", title={V2_STAMP: "Episode title"})],
            clips=[v3_entry("dup", title={V2_STAMP: "Clip title"})],
        ),
    )
    viewer = serve()
    assert "Episode title" in viewer.get("/catalog/vault/episodes/dup").text
    assert "Clip title" in viewer.get("/catalog/vault/clips/dup").text


# Spec: Removed entries (v3) | Remain accessible on detail page
def test_removed_entries_remain_accessible(serve, tmp_path):
    entry = v3_entry("e1", removed={V2_STAMP: False, V2_LATER: True})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    response = serve().get("/catalog/vault/episodes/e1")
    assert response.status_code == 200
    assert "Title e1" in response.text


# Spec: v1 lookup | Lookup in `entries` array when category is `entries`
def test_v1_lookup_uses_the_entries_array(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = serve().get("/catalog/vault/entries/e1")
    assert response.status_code == 200
    assert "Title e1" in response.text


# Spec: v2/v3 lookup | Lookup in matching category array
def test_v2_lookup_uses_the_matching_category_array(serve, tmp_path):
    write_vault(tmp_path, v2_catalog(streams=[v2_entry("s1")]))
    response = serve().get("/catalog/vault/streams/s1")
    assert response.status_code == 200
    assert "Title s1" in response.text


# Spec: v2/v3 lookup | Lookup in matching category array
def test_v3_lookup_uses_the_matching_category_array(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(clips=[v3_entry("c1")]))
    assert "Title c1" in serve().get("/catalog/vault/clips/c1").text


# Spec: Current title | Latest value from `title` history, resolved per version
# key format
def test_current_title_is_the_latest_by_lexicographic_key(serve, tmp_path):
    entry = v3_entry("e1", title={V2_LATER: "Final title", V2_STAMP: "Working title"})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    body = serve().get("/catalog/vault/episodes/e1").text
    assert "Final title" in body
    assert "Working title" not in body


# Spec: Current title | ... resolved per version key format (v1 numeric keys)
def test_v1_current_title_is_the_latest_by_numeric_key(serve, tmp_path):
    entry = v1_entry("e1", title={"999": "Old title", V1_EPOCH: "Final title"})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    body = serve().get("/catalog/vault/entries/e1").text
    assert "Final title" in body
    assert "Old title" not in body


# Spec: Current description | Latest value from `description` history, resolved
# per version key format
def test_current_description_is_the_latest_value(serve, tmp_path):
    entry = v3_entry("e1", description={V2_STAMP: "First text", V2_LATER: "Latest text"})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    body = serve().get("/catalog/vault/episodes/e1").text
    assert "Latest text" in body
    assert "First text" not in body


# Spec: Current description | ... resolved per version key format (v1 numeric keys)
def test_v1_current_description_is_the_latest_by_numeric_key(serve, tmp_path):
    entry = v1_entry("e1", description={"999": "Old text", V1_EPOCH: "Latest text"})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    body = serve().get("/catalog/vault/entries/e1").text
    assert "Latest text" in body
    assert "Old text" not in body


# Spec: Published date | Displayed
def test_published_date_is_displayed(serve, tmp_path):
    entry = v3_entry("e1", published="2023-07-04T12:30:00")
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    assert "2023-07-04" in serve().get("/catalog/vault/episodes/e1").text


# Spec: Dimensions | Display width and height
def test_dimensions_are_displayed(serve, tmp_path):
    entry = v3_entry("e1", width=640, height=360)
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    body = serve().get("/catalog/vault/episodes/e1").text
    assert "640" in body
    assert "360" in body


# Spec: Back navigation | Link to current vault/category listing
def test_back_navigation_links_to_the_category_listing(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(streams=[v3_entry("s1")]))
    assert 'href="/catalog/vault/streams"' in serve().get("/catalog/vault/streams/s1").text


# Spec: Back navigation | Link to current vault/category listing (v1 category)
def test_v1_back_navigation_links_to_the_entries_listing(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    assert 'href="/catalog/vault/entries"' in serve().get("/catalog/vault/entries/e1").text


# Spec: Media playback reference | Use media static endpoint when downloaded
# media file exists
def test_media_reference_uses_the_media_static_endpoint(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    add_media(vault_dir, "e1.mp4")
    assert "/vault/vault/media/e1.mp4" in serve().get("/catalog/vault/episodes/e1").text


# Spec: Downloaded media discovery | A downloaded media file counts as matching
# the entry when a saved filename in `<vault>/media/` contains the entry `id`
def test_media_is_matched_by_a_filename_containing_the_id(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    add_media(vault_dir, "archive-e1-1080p.webm")
    assert "/vault/vault/media/" in serve().get("/catalog/vault/episodes/e1").text


# Spec: Downloaded media discovery | ... the detail page uses that exact
# filename in the media static endpoint URL
def test_media_reference_uses_the_exact_saved_filename(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    add_media(vault_dir, "archive-e1-1080p.webm")
    body = serve().get("/catalog/vault/episodes/e1").text
    assert "/vault/vault/media/archive-e1-1080p.webm" in body


# Spec: Missing downloaded media | Keep metadata and chart data visible
def test_missing_media_keeps_the_metadata_visible(serve, tmp_path):
    entry = v3_entry("e1", width=640, height=360, published="2023-07-04T12:30:00")
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    response = serve().get("/catalog/vault/episodes/e1")
    assert response.status_code == 200
    assert "Title e1" in response.text
    assert "2023-07-04" in response.text
    assert "/vault/vault/media/" not in response.text


# Spec: Missing downloaded media | Keep metadata and chart data visible
def test_missing_media_keeps_the_chart_data_visible(serve, tmp_path):
    entry = v3_entry("e1", views={V2_STAMP: 10, V2_LATER: 40})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    body = serve().get("/catalog/vault/episodes/e1").text
    assert chart_points(body, "views") == [(V2_STAMP, 10), (V2_LATER, 40)]
