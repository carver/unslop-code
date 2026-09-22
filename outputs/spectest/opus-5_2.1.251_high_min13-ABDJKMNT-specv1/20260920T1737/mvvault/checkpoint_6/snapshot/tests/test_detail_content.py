"""Spec section: `/catalog/<name>/<category>/<id>` Page Content."""

import pytest
from conftest import chart_points, write_media, write_previews
from detail_fixtures import (
    EPOCH_NEW,
    VERSION_CASES,
    v1_vault,
    v3_vault,
)

PUBLISHED = "2024-01-01T00:00:00"


def detail(viewer, category="episodes", entry_id="e1"):
    return viewer.client.get(f"/catalog/demo/{category}/{entry_id}")


# Phrase: "| Current title | Latest value from `title` history, resolved per
# version key format |".
@pytest.mark.parametrize("build, category, entry_id", VERSION_CASES)
def test_current_title_is_the_latest_history_value(viewer, tmp_path, build, category, entry_id):
    build(tmp_path)

    body = detail(viewer, category, entry_id).body

    assert f"new-title-{entry_id}" in body
    assert f"old-title-{entry_id}" not in body


# Phrase: "| Current description | Latest value from `description` history,
# resolved per version key format |".
@pytest.mark.parametrize("build, category, entry_id", VERSION_CASES)
def test_current_description_is_the_latest_history_value(viewer, tmp_path, build, category, entry_id):
    build(tmp_path)

    body = detail(viewer, category, entry_id).body

    assert f"new-description-{entry_id}" in body
    assert f"old-description-{entry_id}" not in body


# Phrase: "| Current tracked value (v1) | Value at latest key by numeric
# comparison |" -- lexicographically `999999999` would win instead.
def test_v1_current_value_uses_numeric_key_comparison(viewer, tmp_path):
    v1_vault(tmp_path)

    body = detail(viewer, "entries").body

    assert "new-title-e1" in body
    assert "old-title-e1" not in body


# Phrase: "| Published date | Displayed |".
@pytest.mark.parametrize("build, category, entry_id", VERSION_CASES)
def test_published_date_is_displayed(viewer, tmp_path, build, category, entry_id):
    build(tmp_path)

    assert PUBLISHED in detail(viewer, category, entry_id).body


# Phrase: "| Dimensions | Display width and height |".
@pytest.mark.parametrize("build, category, entry_id", VERSION_CASES)
def test_dimensions_are_displayed(viewer, tmp_path, build, category, entry_id):
    build(tmp_path)

    body = detail(viewer, category, entry_id).body

    assert "1920" in body
    assert "1080" in body


# Phrase: "| Back navigation | Link to current vault/category listing |".
@pytest.mark.parametrize("build, category, entry_id", VERSION_CASES)
def test_back_navigation_links_to_the_category_listing(viewer, tmp_path, build, category, entry_id):
    build(tmp_path)

    body = detail(viewer, category, entry_id).body

    assert f'href="/catalog/demo/{category}"' in body


# Phrase: "| Back navigation | Link to current vault/category listing |" -- the
# link leads to a listing that really serves this category.
def test_back_navigation_target_is_servable(viewer, tmp_path):
    v3_vault(tmp_path)
    detail(viewer)

    listing = viewer.client.get("/catalog/demo/episodes")

    assert listing.status == 200


# Phrase: "| Media playback reference | Use media static endpoint when
# downloaded media file exists |".
def test_media_playback_reference_uses_the_static_endpoint(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_media(vault, "e1.mp4")

    assert "/vault/demo/media/e1.mp4" in detail(viewer).body


# Phrase: "| Downloaded media discovery | A downloaded media file counts as
# matching the entry when a saved filename in `<vault>/media/` contains the
# entry `id` ... uses that exact filename |".
def test_media_discovery_matches_a_filename_containing_the_id(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_media(vault, "2024-episode-e1-1080p.mp4")

    assert "/vault/demo/media/2024-episode-e1-1080p.mp4" in detail(viewer).body


# Phrase: "| Downloaded media reference | When rendered, the detail page uses
# the matched saved filename in `/vault/<name>/media/<file>` |" -- media stored
# for another entry is not referenced here.
def test_media_of_another_entry_is_not_referenced(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_media(vault, "s1.mp4")

    assert "/vault/demo/media/s1.mp4" not in detail(viewer).body


# Phrase: "| Missing downloaded media | Keep metadata and chart data visible |".
def test_missing_media_keeps_metadata_and_chart_data(viewer, tmp_path):
    v3_vault(tmp_path)

    response = detail(viewer)

    assert response.status == 200
    assert "new-title-e1" in response.body
    assert PUBLISHED in response.body
    assert "/vault/demo/media/" not in response.body
    assert chart_points(response.body, "views") is not None


# Phrase: "| Source-platform link | Deterministic URL derived from vault source
# information and entry `id` |" -- the same request renders the same page.
def test_detail_page_is_deterministic(viewer, tmp_path):
    v3_vault(tmp_path)

    assert detail(viewer).body == detail(viewer).body


# Phrase: "| Preview lookup | `/vault/<name>/preview/<id>` resolves the saved
# preview asset ... |" -- a stored preview is reachable from the detail page.
def test_stored_preview_is_referenced_by_the_detail_page(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_previews(vault, "e1.jpg")

    assert "/vault/demo/preview/e1" in detail(viewer).body


# Phrase: "| v1 | UNIX-epoch string ... |" -- a v1 detail page is served from
# the flat `entries` array with its epoch-keyed histories intact.
def test_v1_detail_page_renders_from_epoch_keyed_histories(viewer, tmp_path):
    v1_vault(tmp_path)

    body = detail(viewer, "entries").body

    assert "new-title-e1" in body
    assert EPOCH_NEW not in body
