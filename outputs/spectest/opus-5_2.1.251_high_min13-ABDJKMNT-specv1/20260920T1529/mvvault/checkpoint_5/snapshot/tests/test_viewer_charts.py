"""Spec sections: `views` and `likes` Chart Data, its version-aware timestamp
normalization, and its ordering across versions."""

from conftest import (
    V1_KEY,
    V1_OLDER_KEY,
    V2_KEY,
    V2_OLDER_KEY,
    chart_payload,
    chart_points,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

SOURCE = "https://example.test/a"

# `999999999` is text-greater than `1718444400` but numerically smaller: the
# epoch second of 2001-09-09T01:46:39 UTC.
V1_TEXT_GREATER_KEY = "999999999"
V1_TEXT_GREATER_ISO = "2001-09-09T01:46:39"
V1_ISO = "2024-06-15T09:40:00"
V1_OLDER_ISO = "2023-11-14T22:13:20"


def tracked_vault(tmp_path, **histories):
    """A v3 vault holding one episode whose tracked histories are given."""
    entry = v3_entry("e1", **histories)
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[entry]))
    return "/catalog/demo/episodes/e1"


# Chart Data: "Fields exposed | `views`, `likes`"; "Embedding style |
# Machine-readable structured data embedded in HTML".
def test_views_and_likes_are_embedded_as_machine_readable_data(viewer, tmp_path):
    route = tracked_vault(
        tmp_path,
        views={V2_OLDER_KEY: 10, V2_KEY: 20},
        likes={V2_OLDER_KEY: 1, V2_KEY: 2},
    )

    payload = chart_payload(viewer.get(route).body)

    assert "views" in payload
    assert "likes" in payload


# Chart Data: "Point payload | Preserve timestamp/value pairing".
def test_points_preserve_their_timestamp_value_pairing(viewer, tmp_path):
    route = tracked_vault(tmp_path, views={V2_OLDER_KEY: 10, V2_KEY: 20})

    points = chart_points(viewer.get(route).body, "views")

    assert points == [(V2_OLDER_KEY, 10), (V2_KEY, 20)]


# Chart Data: "Point payload | ... `likes` may use `null`; no filtering or
# replacement"; Determinism: "`likes` nulls | Preserved in chart data".
def test_null_likes_are_preserved_as_points(viewer, tmp_path):
    route = tracked_vault(tmp_path, likes={V2_OLDER_KEY: None, V2_KEY: 7})

    points = chart_points(viewer.get(route).body, "likes")

    assert points == [(V2_OLDER_KEY, None), (V2_KEY, 7)]


# Chart Data: "Point payload | ... no filtering or replacement" — a repeated
# value is still its own point.
def test_every_recorded_point_is_kept(viewer, tmp_path):
    keys = {"2024-01-01T00:00:00": 5, "2024-02-01T00:00:00": 5, "2024-03-01T00:00:00": 9}
    route = tracked_vault(tmp_path, views=keys)

    points = chart_points(viewer.get(route).body, "views")

    assert points == [("2024-01-01T00:00:00", 5), ("2024-02-01T00:00:00", 5), ("2024-03-01T00:00:00", 9)]


# Chart Data: "Point order | Chronological, oldest first" — the catalog stores
# the newer key first, the chart still starts with the older one.
def test_points_are_ordered_oldest_first(viewer, tmp_path):
    route = tracked_vault(tmp_path, views={V2_KEY: 20, V2_OLDER_KEY: 10})

    points = chart_points(viewer.get(route).body, "views")

    assert points == [(V2_OLDER_KEY, 10), (V2_KEY, 20)]


# Chart Data: "Single-point history | Chart for that field may be omitted" —
# the page is still served.
def test_single_point_history_still_serves_the_page(viewer, tmp_path):
    route = tracked_vault(tmp_path, views={V2_KEY: 10}, likes={V2_KEY: 5})

    response = viewer.get(route)

    assert response.status == 200
    assert "Traceback" not in response.body


# Chart Data: "Metadata without chart | Title, description, published date,
# dimensions, and source link still render".
def test_metadata_renders_without_any_chart(viewer, tmp_path):
    entry = v3_entry("e1", published="2021-03-04T05:06:07", width=640, height=360)
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[entry]))

    body = viewer.get("/catalog/demo/episodes/e1").body

    assert "title-e1" in body
    assert "description-e1" in body
    assert "2021-03-04T05:06:07" in body
    assert "640" in body and "360" in body
    assert f"{SOURCE}/entry/e1" in body


# Timestamp Normalization: "v1 | UNIX-epoch string ... | Convert to ISO 8601
# UTC"; Determinism: "Chart output timestamps | Always ISO 8601 regardless of
# vault version".
def test_v1_epoch_keys_become_iso_timestamps(viewer, tmp_path):
    entry = v1_entry("e1", views={V1_OLDER_KEY: 10, V1_KEY: 20})
    write_vault(tmp_path, v1_catalog([entry]))

    points = chart_points(viewer.get("/catalog/demo/entries/e1").body, "views")

    assert points == [(V1_OLDER_ISO, 10), (V1_ISO, 20)]


# Timestamp Normalization: "v1 | ... Convert to ISO 8601 UTC" — the raw epoch
# key is not what the chart carries.
def test_v1_chart_does_not_carry_raw_epoch_keys(viewer, tmp_path):
    entry = v1_entry("e1", views={V1_OLDER_KEY: 10, V1_KEY: 20})
    write_vault(tmp_path, v1_catalog([entry]))

    timestamps = [point[0] for point in chart_points(viewer.get("/catalog/demo/entries/e1").body, "views")]

    assert V1_KEY not in timestamps
    assert V1_OLDER_KEY not in timestamps


# Timestamp Normalization: "v2 | ISO 8601 string | Pass through".
def test_v2_iso_keys_pass_through(viewer, tmp_path):
    entry = v2_entry("e1", views={V2_OLDER_KEY: 10, V2_KEY: 20})
    write_vault(tmp_path, v2_catalog(SOURCE, episodes=[entry]))

    points = chart_points(viewer.get("/catalog/demo/episodes/e1").body, "views")

    assert points == [(V2_OLDER_KEY, 10), (V2_KEY, 20)]


# Timestamp Normalization: "v3 | ISO 8601 string | Pass through".
def test_v3_iso_keys_pass_through(viewer, tmp_path):
    route = tracked_vault(tmp_path, views={V2_OLDER_KEY: 10, V2_KEY: 20})

    points = chart_points(viewer.get(route).body, "views")

    assert points == [(V2_OLDER_KEY, 10), (V2_KEY, 20)]


# Ordering Across Versions: "v1 | Numeric comparison of UNIX-epoch string
# keys"; Determinism: "v1 chart ordering | By numeric epoch value, not
# lexicographic".
def test_v1_points_order_numerically_not_lexicographically(viewer, tmp_path):
    entry = v1_entry("e1", views={V1_TEXT_GREATER_KEY: 3, V1_KEY: 4})
    write_vault(tmp_path, v1_catalog([entry]))

    points = chart_points(viewer.get("/catalog/demo/entries/e1").body, "views")

    assert points == [(V1_TEXT_GREATER_ISO, 3), (V1_ISO, 4)]


# Ordering Across Versions: "v2 | Lexicographic comparison of ISO 8601 string
# keys".
def test_v2_points_order_lexicographically(viewer, tmp_path):
    entry = v2_entry("e1", likes={V2_KEY: 9, V2_OLDER_KEY: None})
    write_vault(tmp_path, v2_catalog(SOURCE, episodes=[entry]))

    points = chart_points(viewer.get("/catalog/demo/episodes/e1").body, "likes")

    assert points == [(V2_OLDER_KEY, None), (V2_KEY, 9)]


# Ordering Across Versions: "v3 | Lexicographic comparison of ISO 8601 string
# keys".
def test_v3_points_order_lexicographically(viewer, tmp_path):
    route = tracked_vault(tmp_path, views={"2024-10-02T00:00:00": 3, "2024-10-01T00:00:00": 1})

    points = chart_points(viewer.get(route).body, "views")

    assert points == [("2024-10-01T00:00:00", 1), ("2024-10-02T00:00:00", 3)]


# Determinism: "Chart point order | Chronological, oldest first" — the same
# vault and entry answer identically on every request.
def test_chart_data_is_identical_across_requests(viewer, tmp_path):
    route = tracked_vault(tmp_path, views={V2_KEY: 20, V2_OLDER_KEY: 10})

    assert viewer.get(route).body == viewer.get(route).body
