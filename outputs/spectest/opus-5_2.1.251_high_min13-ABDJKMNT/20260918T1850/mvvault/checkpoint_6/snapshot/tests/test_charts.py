"""Spec sections: `views` and `likes` Chart Data, Chart Data -- Version-Aware
Timestamp Normalization, Chart Data -- Ordering Across Versions."""

from conftest import (
    V1_EPOCH,
    V1_EPOCH_ISO,
    V2_LATER,
    V2_STAMP,
    chart_data,
    chart_points,
    charted_fields,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

#: A third ISO 8601 key, for histories that need more than two points.
V2_LATEST = "2024-06-17T09:40:00"

#: A second UNIX-epoch key, ordering *before* `V1_EPOCH` numerically but after
#: it lexicographically.
V1_EARLY_EPOCH = "999"
V1_EARLY_ISO = "1970-01-01T00:16:39"


def detail(serve, tmp_path, entry, category="episodes"):
    """Serve a one-entry v3 vault and return its detail page."""
    write_vault(tmp_path, v3_catalog(**{category: [entry]}))
    return serve().get(f"/catalog/vault/{category}/{entry['id']}").text


# Spec: Fields exposed | `views`, `likes`
def test_both_tracked_counts_are_exposed(serve, tmp_path):
    entry = v3_entry("e1", views={V2_STAMP: 10, V2_LATER: 40}, likes={V2_STAMP: 1, V2_LATER: 3})
    assert set(chart_data(detail(serve, tmp_path, entry))) == {"views", "likes"}


# Spec: Embedding style | Machine-readable structured data embedded in HTML
def test_chart_data_is_machine_readable(serve, tmp_path):
    entry = v3_entry("e1", views={V2_STAMP: 10, V2_LATER: 40})
    assert chart_data(detail(serve, tmp_path, entry))["views"]


# Spec: Point payload | Preserve timestamp/value pairing
def test_points_pair_each_timestamp_with_its_value(serve, tmp_path):
    entry = v3_entry("e1", views={V2_STAMP: 10, V2_LATER: 40})
    body = detail(serve, tmp_path, entry)
    assert chart_points(body, "views") == [(V2_STAMP, 10), (V2_LATER, 40)]


# Spec: Point payload | `likes` may use `null`
def test_null_likes_are_preserved(serve, tmp_path):
    entry = v3_entry("e1", likes={V2_STAMP: 2, V2_LATER: None})
    body = detail(serve, tmp_path, entry)
    assert chart_points(body, "likes") == [(V2_STAMP, 2), (V2_LATER, None)]


# Spec: Point payload | ... no filtering or replacement
def test_no_point_is_filtered_out(serve, tmp_path):
    views = {V2_STAMP: 10, V2_LATER: 10, V2_LATEST: 40}
    entry = v3_entry("e1", views=views)
    body = detail(serve, tmp_path, entry)
    assert chart_points(body, "views") == [(V2_STAMP, 10), (V2_LATER, 10), (V2_LATEST, 40)]


# Spec: Point order | Chronological, oldest first
def test_points_are_chronological_oldest_first(serve, tmp_path):
    entry = v3_entry("e1", views={V2_LATEST: 40, V2_STAMP: 10, V2_LATER: 25})
    body = detail(serve, tmp_path, entry)
    assert [point[0] for point in chart_points(body, "views")] == [
        V2_STAMP,
        V2_LATER,
        V2_LATEST,
    ]


# Spec: Single-point history | Chart for that field may be omitted
def test_a_single_point_field_is_not_charted(serve, tmp_path):
    entry = v3_entry("e1", views={V2_STAMP: 10}, likes={V2_STAMP: 1, V2_LATER: 3})
    body = detail(serve, tmp_path, entry)
    assert charted_fields(body) == ["likes"]


# Spec: Metadata without chart | Title, description, published date, dimensions,
# and source link still render
def test_metadata_renders_without_any_chart(serve, tmp_path):
    entry = v3_entry("e1", width=640, height=360, published="2023-07-04T12:30:00")
    body = detail(serve, tmp_path, entry)
    assert charted_fields(body) == []
    assert "Title e1" in body
    assert "Description e1" in body
    assert "2023-07-04" in body
    assert "640" in body
    assert "360" in body
    assert "/entry/e1" in body


# Spec: v2 | ISO 8601 string | Pass through
def test_v2_timestamps_pass_through(serve, tmp_path):
    entry = v2_entry("e1", views={V2_STAMP: 10, V2_LATER: 40})
    write_vault(tmp_path, v2_catalog(episodes=[entry]))
    body = serve().get("/catalog/vault/episodes/e1").text
    assert [point[0] for point in chart_points(body, "views")] == [V2_STAMP, V2_LATER]


# Spec: v3 | ISO 8601 string | Pass through
def test_v3_timestamps_pass_through(serve, tmp_path):
    entry = v3_entry("e1", views={V2_STAMP: 10, V2_LATER: 40})
    body = detail(serve, tmp_path, entry)
    assert [point[0] for point in chart_points(body, "views")] == [V2_STAMP, V2_LATER]


# Spec: v1 | UNIX-epoch string (e.g., `"1718444400"`) | Convert to ISO 8601 UTC
def test_v1_epoch_timestamps_become_iso_8601_utc(serve, tmp_path):
    entry = v1_entry("e1", views={V1_EPOCH: 10})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    body = serve().get("/catalog/vault/entries/e1").text
    assert chart_points(body, "views") == [(V1_EPOCH_ISO, 10)]


# Spec: Chart output timestamps | Always ISO 8601 regardless of vault version
def test_v1_raw_epoch_keys_are_not_emitted(serve, tmp_path):
    entry = v1_entry("e1", views={V1_EPOCH: 10})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    body = serve().get("/catalog/vault/entries/e1").text
    assert V1_EPOCH not in str(chart_data(body))


# Spec: v1 | Numeric comparison of UNIX-epoch string keys
# Spec: v1 chart ordering | By numeric epoch value, not lexicographic
def test_v1_points_order_by_numeric_epoch_value(serve, tmp_path):
    entry = v1_entry("e1", views={V1_EPOCH: 40, V1_EARLY_EPOCH: 10})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    body = serve().get("/catalog/vault/entries/e1").text
    assert chart_points(body, "views") == [(V1_EARLY_ISO, 10), (V1_EPOCH_ISO, 40)]


# Spec: v2/v3 | Lexicographic comparison of ISO 8601 string keys
def test_v3_points_order_lexicographically(serve, tmp_path):
    entry = v3_entry("e1", views={V2_LATEST: 40, V2_STAMP: 10})
    body = detail(serve, tmp_path, entry)
    assert chart_points(body, "views") == [(V2_STAMP, 10), (V2_LATEST, 40)]


# Spec: `likes` nulls | Preserved in chart data (v1 vaults too)
def test_v1_null_likes_are_preserved(serve, tmp_path):
    entry = v1_entry("e1", likes={V1_EARLY_EPOCH: 2, V1_EPOCH: None})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    body = serve().get("/catalog/vault/entries/e1").text
    assert chart_points(body, "likes") == [(V1_EARLY_ISO, 2), (V1_EPOCH_ISO, None)]


# Spec: Chart point order | Chronological, oldest first (stable across requests)
def test_chart_data_is_stable_across_requests(serve, tmp_path):
    entry = v3_entry("e1", views={V2_LATEST: 40, V2_STAMP: 10, V2_LATER: 25})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    viewer = serve()
    first = chart_data(viewer.get("/catalog/vault/episodes/e1").text)
    assert first == chart_data(viewer.get("/catalog/vault/episodes/e1").text)
