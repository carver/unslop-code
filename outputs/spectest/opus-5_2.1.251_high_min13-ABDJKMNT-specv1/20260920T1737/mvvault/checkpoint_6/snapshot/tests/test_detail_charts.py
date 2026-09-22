"""Spec section: `views` and `likes` Chart Data."""

import pytest
from conftest import ISO_KEY, chart_points, embedded_json, point_pairs, v3_catalog, v3_entry, write_vault
from detail_fixtures import ISO_NEW, ISO_OLD, VERSION_CASES, v3_vault


def points(viewer, field, category="episodes", entry_id="e1"):
    return chart_points(viewer.client.get(f"/catalog/demo/{category}/{entry_id}").body, field)


# Phrase: "| Fields exposed | `views`, `likes` |".
@pytest.mark.parametrize("field", ["views", "likes"])
@pytest.mark.parametrize("build, category, entry_id", VERSION_CASES)
def test_both_tracked_fields_are_exposed(viewer, tmp_path, build, category, entry_id, field):
    build(tmp_path)

    assert points(viewer, field, category, entry_id) is not None


# Phrase: "| Embedding style | Machine-readable structured data embedded in
# HTML |".
def test_chart_data_is_embedded_as_machine_readable_data(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/episodes/e1")

    assert response.headers["Content-Type"].startswith("text/html")
    assert embedded_json(response.body), "no machine-readable payload was embedded"


# Phrase: "| Point payload | Preserve timestamp/value pairing ... |".
def test_points_preserve_the_timestamp_value_pairing(viewer, tmp_path):
    v3_vault(tmp_path)

    assert point_pairs(points(viewer, "views")) == [(ISO_OLD, 100), (ISO_NEW, 250)]


# Phrase: "| Point payload | ... `likes` may use `null`; no filtering or
# replacement |".
def test_null_likes_are_preserved_rather_than_filtered(viewer, tmp_path):
    v3_vault(tmp_path)

    assert point_pairs(points(viewer, "likes")) == [(ISO_OLD, 7), (ISO_NEW, None)]


# Phrase: "| `likes` nulls | Preserved in chart data |" -- a history that is
# null throughout keeps every point.
def test_all_null_likes_history_keeps_every_point(viewer, tmp_path):
    entry = v3_entry("e1", likes={ISO_OLD: None, ISO_NEW: None})
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[entry]))

    assert point_pairs(points(viewer, "likes")) == [(ISO_OLD, None), (ISO_NEW, None)]


# Phrase: "| Point payload | ... no filtering or replacement |" -- repeated
# values are points of their own, not collapsed.
def test_repeated_values_are_not_collapsed(viewer, tmp_path):
    middle = "2024-03-04T05:06:07"
    entry = v3_entry("e1", views={ISO_OLD: 100, middle: 100, ISO_NEW: 100})
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[entry]))

    assert point_pairs(points(viewer, "views")) == [(ISO_OLD, 100), (middle, 100), (ISO_NEW, 100)]


# Phrase: "| Point order | Chronological, oldest first |".
@pytest.mark.parametrize("field", ["views", "likes"])
def test_points_are_ordered_oldest_first(viewer, tmp_path, field):
    v3_vault(tmp_path)

    stamps = [stamp for stamp, _ in point_pairs(points(viewer, field))]

    assert stamps == [ISO_OLD, ISO_NEW]


# Phrase: "| Single-point history | Chart for that field may be omitted |" --
# the page is still served for a history holding one point.
def test_single_point_history_still_serves_the_page(viewer, tmp_path):
    entry = v3_entry("e1", views={ISO_KEY: 10})
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[entry]))

    assert viewer.client.get("/catalog/demo/episodes/e1").status == 200


# Phrase: "| Metadata without chart | Title, description, published date,
# dimensions, and source link still render |".
def test_metadata_renders_when_no_chart_can_be_drawn(viewer, tmp_path):
    entry = v3_entry("e1", views={ISO_KEY: 10}, likes={ISO_KEY: 4})
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[entry]))

    body = viewer.client.get("/catalog/demo/episodes/e1").body

    assert "title-e1" in body
    assert "description-e1" in body
    assert "2024-01-01T00:00:00" in body
    assert "1920" in body and "1080" in body
    assert "https://example.test/feed/entry/e1" in body


# Phrase: "| Fields exposed | `views`, `likes` |" -- the chart data covers the
# requested entry only, not its siblings.
def test_chart_data_belongs_to_the_requested_entry(viewer, tmp_path):
    entry = v3_entry("e1", views={ISO_OLD: 100, ISO_NEW: 250})
    other = v3_entry("e2", views={ISO_OLD: 1, ISO_NEW: 2})
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[entry, other]))

    assert point_pairs(points(viewer, "views", entry_id="e2")) == [(ISO_OLD, 1), (ISO_NEW, 2)]
