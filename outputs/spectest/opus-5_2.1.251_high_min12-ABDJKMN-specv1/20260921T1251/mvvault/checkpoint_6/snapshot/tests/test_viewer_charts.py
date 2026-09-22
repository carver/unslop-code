"""Spec section: `views` and `likes` chart data, and its version normalization."""

from __future__ import annotations

import re

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

# Two v1 keys whose numeric order is the opposite of their text order:
# "900000000" (1998) sorts after "1718444400" (2024) as text.
V1_OLD = "900000000"
V1_OLD_ISO = "1998-07-09T16:00:00"


# ---------------------------------------------------------------------------
# | Fields exposed | `views`, `likes` |
# | Embedding style | Machine-readable structured data embedded in HTML |
# ---------------------------------------------------------------------------

# Spec: | Embedding style | Machine-readable structured data embedded in HTML |
def test_detail_page_embeds_machine_readable_data(serve, make_vault, catalogs,
                                                  detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 10, catalogs.STAMP_2: 20}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.json_blocks(page), page


# Spec: | Fields exposed | `views`, `likes` |
def test_both_fields_are_exposed(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 10, catalogs.STAMP_2: 20}
    entry["likes"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 2}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    series = detail.series(page)
    assert set(series) >= {"views", "likes"}, series


# Spec: | Fields exposed | `views`, `likes` |
# Context: untracked fields are not chart data; `title` is not a series.
def test_title_history_is_not_charted(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 10, catalogs.STAMP_2: 20}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert "title" not in detail.series(page)


# ---------------------------------------------------------------------------
# | Point payload | Preserve timestamp/value pairing; `likes` may use `null`;
#   no filtering or replacement |
# ---------------------------------------------------------------------------

# Spec: | Point payload | Preserve timestamp/value pairing ... |
def test_points_pair_timestamps_with_values(serve, make_vault, catalogs,
                                            detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 11, catalogs.STAMP_2: 22,
                      catalogs.STAMP_3: 33}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.points(page, "views") == [
        (catalogs.STAMP_1, 11), (catalogs.STAMP_2, 22), (catalogs.STAMP_3, 33)]


# Spec: | Point payload | ... `likes` may use `null` ... |
def test_null_likes_are_preserved(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["likes"] = {catalogs.STAMP_1: 5, catalogs.STAMP_2: None,
                      catalogs.STAMP_3: 7}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.values(page, "likes") == [5, None, 7]


# Spec: | Point payload | ... no filtering or replacement |
# Context: an all-null `likes` history is charted as nulls, not dropped and not
# replaced with zeroes.
def test_all_null_likes_are_not_filtered(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["likes"] = {catalogs.STAMP_1: None, catalogs.STAMP_2: None}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.points(page, "likes") == [
        (catalogs.STAMP_1, None), (catalogs.STAMP_2, None)]


# Spec: | Point payload | ... no filtering or replacement |
# Context: repeated and zero values survive; nothing is deduplicated.
def test_repeated_and_zero_values_survive(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 0, catalogs.STAMP_2: 0,
                      catalogs.STAMP_3: 0}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.values(page, "views") == [0, 0, 0]


# Spec: | Point payload | ... no filtering or replacement |
# Context: a decreasing series is charted as recorded.
def test_decreasing_values_are_not_reordered_by_value(serve, make_vault,
                                                      catalogs, detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 500, catalogs.STAMP_2: 100,
                      catalogs.STAMP_3: 300}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.values(page, "views") == [500, 100, 300]


# ---------------------------------------------------------------------------
# | Point order | Chronological, oldest first |
# ---------------------------------------------------------------------------

# Spec: | Point order | Chronological, oldest first |
def test_points_are_oldest_first(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    # Written newest-first in the catalog; the page must not echo that order.
    entry["views"] = {catalogs.STAMP_3: 3, catalogs.STAMP_1: 1,
                      catalogs.STAMP_2: 2}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.timestamps(page, "views") == [
        catalogs.STAMP_1, catalogs.STAMP_2, catalogs.STAMP_3]


# Spec: | Point order | Chronological, oldest first |
# Context: `likes` is ordered the same way as `views`.
def test_likes_points_are_oldest_first(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["likes"] = {catalogs.STAMP_2: 2, catalogs.STAMP_1: 1}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.values(page, "likes") == [1, 2]


# ---------------------------------------------------------------------------
# | v1 | UNIX-epoch string (e.g., `"1718444400"`) | Convert to ISO 8601 UTC |
# | v2 | ISO 8601 string | Pass through |
# | v3 | ISO 8601 string | Pass through |
# ---------------------------------------------------------------------------

# Spec: | v1 | UNIX-epoch string ... | Convert to ISO 8601 UTC |
def test_v1_epoch_keys_become_iso_8601(serve, make_vault, legacy, detail):
    entry = legacy.v1_entry("e1")
    entry["views"] = {legacy.V1_EPOCH: 100}
    make_vault(legacy.v1_catalog(entries=[entry]))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert detail.timestamps(page, "views") == [legacy.V1_EPOCH_ISO]


# Spec: | v1 | ... | Convert to ISO 8601 UTC |
# Context: the raw epoch string is not what the chart data carries.
def test_v1_chart_timestamps_are_never_raw_epochs(serve, make_vault, legacy,
                                                  detail):
    entry = legacy.v1_entry("e1")
    entry["views"] = {legacy.V1_EPOCH: 100, legacy.V1_EPOCH_LATER: 200}
    make_vault(legacy.v1_catalog(entries=[entry]))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    stamps = detail.timestamps(page, "views")
    assert stamps == [legacy.V1_EPOCH_ISO, legacy.V1_EPOCH_LATER_ISO]
    assert all(ISO_RE.match(stamp) for stamp in stamps), stamps


# Spec: | Chart output timestamps | Always ISO 8601 regardless of vault version |
# Context: the conversion is UTC, so a pre-2000 epoch lands in 1998.
def test_v1_epoch_conversion_is_utc(serve, make_vault, legacy, detail):
    entry = legacy.v1_entry("e1")
    entry["views"] = {V1_OLD: 1}
    make_vault(legacy.v1_catalog(entries=[entry]))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert detail.timestamps(page, "views") == [V1_OLD_ISO]


# Spec: | v2 | ISO 8601 string | Pass through |
def test_v2_timestamps_pass_through(serve, make_vault, legacy, detail):
    entry = legacy.v2_entry("e1")
    entry["views"] = {"2024-06-15T09:40:00": 10,
                      "2024-07-01T00:00:00": 20}
    make_vault(legacy.v2_catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.timestamps(page, "views") == ["2024-06-15T09:40:00",
                                                "2024-07-01T00:00:00"]


# Spec: | v3 | ISO 8601 string | Pass through |
def test_v3_timestamps_pass_through(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 10, catalogs.STAMP_2: 20}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.timestamps(page, "views") == [catalogs.STAMP_1,
                                                catalogs.STAMP_2]


# Spec: | Chart output timestamps | Always ISO 8601 regardless of vault version |
# Context: the same instant charts identically from a v1 and a v3 vault.
def test_chart_timestamps_are_uniform_across_versions(serve, make_vault,
                                                      legacy, catalogs, detail):
    v1_entry = legacy.v1_entry("e1")
    v1_entry["views"] = {legacy.V1_EPOCH: 42}
    make_vault(legacy.v1_catalog(entries=[v1_entry]), name="one")

    v3_entry = catalogs.entry("e1")
    v3_entry["views"] = {legacy.V1_EPOCH_ISO: 42}
    make_vault(catalogs.catalog(episodes=[v3_entry]), name="three")

    client = serve().client
    first = client.get(detail.path("one", "entries", "e1")).body
    second = client.get(detail.path("three", "episodes", "e1")).body
    assert detail.points(first, "views") == detail.points(second, "views")


# ---------------------------------------------------------------------------
# | v1 | Numeric comparison of UNIX-epoch string keys |
# | v2 | Lexicographic comparison of ISO 8601 string keys |
# | v3 | Lexicographic comparison of ISO 8601 string keys |
# ---------------------------------------------------------------------------

# Spec: | v1 | Numeric comparison of UNIX-epoch string keys |
# Context: `"900000000"` is older than `"1718444400"` numerically but sorts
# after it as text, so a lexicographic implementation gets this backwards.
def test_v1_ordering_is_numeric_not_lexicographic(serve, make_vault, legacy,
                                                  detail):
    entry = legacy.v1_entry("e1")
    entry["views"] = {legacy.V1_EPOCH: 200, V1_OLD: 100}
    make_vault(legacy.v1_catalog(entries=[entry]))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert detail.points(page, "views") == [
        (V1_OLD_ISO, 100), (legacy.V1_EPOCH_ISO, 200)]


# Spec: | v1 | Numeric comparison ... |
# Context: epoch keys of differing digit counts stay in numeric order.
def test_v1_ordering_handles_short_and_long_keys(serve, make_vault, legacy,
                                                 detail):
    entry = legacy.v1_entry("e1")
    entry["views"] = {"1718444400": 3, "99999999": 1, "900000000": 2}
    make_vault(legacy.v1_catalog(entries=[entry]))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert detail.values(page, "views") == [1, 2, 3]


# Spec: | v2 | Lexicographic comparison of ISO 8601 string keys |
def test_v2_ordering_is_lexicographic(serve, make_vault, legacy, detail):
    entry = legacy.v2_entry("e1")
    entry["views"] = {"2024-12-01T00:00:00": 3,
                      "2024-02-01T00:00:00": 1,
                      "2024-07-01T00:00:00": 2}
    make_vault(legacy.v2_catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.values(page, "views") == [1, 2, 3]


# Spec: | v3 | Lexicographic comparison of ISO 8601 string keys |
def test_v3_ordering_is_lexicographic(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["likes"] = {"2025-01-01T00:00:00": 3,
                      "2024-01-01T00:00:00": 1,
                      "2024-06-01T00:00:00": 2}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert detail.values(page, "likes") == [1, 2, 3]


# ---------------------------------------------------------------------------
# | Single-point history | Chart for that field may be omitted |
# | Metadata without chart | Title, description, published date, dimensions,
#   and source link still render |
# ---------------------------------------------------------------------------

# Spec: | Single-point history | Chart for that field may be omitted |
# Context: omitting is permitted, so the page just has to stay well-formed -
# and any points it does publish must still be the recorded ones.
def test_single_point_history_is_answered(serve, make_vault, catalogs, detail):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 7}
    make_vault(catalogs.catalog(episodes=[entry]))
    response = serve().client.get(detail.path("vault", "episodes", "e1"))
    assert response.status == 200, response.status
    points = detail.points(response.body, "views")
    assert points in ([], [(catalogs.STAMP_1, 7)]), points


# Spec: | Metadata without chart | Title, description, published date,
#   dimensions, and source link still render |
def test_metadata_renders_without_any_chart(serve, make_vault, catalogs,
                                            source, detail):
    entry = catalogs.entry("e1")
    entry["published"] = "2021-03-04T05:06:07"
    entry["width"] = 1280
    entry["height"] = 720
    entry["views"] = {catalogs.STAMP_1: 7}
    entry["likes"] = {catalogs.STAMP_1: 1}
    make_vault(catalogs.catalog(episodes=[entry]))
    page = serve().client.get(detail.path("vault", "episodes", "e1")).body
    assert "Title e1" in page
    assert "Description e1" in page
    assert "2021-03-04T05:06:07" in page
    assert "1280" in page and "720" in page
    assert f"{source.url}/entry/e1" in page


# Spec: | Metadata without chart | ... still render |
# Context: an entry with no tracked history at all still renders its metadata.
def test_metadata_renders_with_empty_histories(serve, make_vault, catalogs,
                                               source, detail):
    entry = catalogs.entry("e1")
    entry["views"] = {}
    entry["likes"] = {}
    make_vault(catalogs.catalog(episodes=[entry]))
    response = serve().client.get(detail.path("vault", "episodes", "e1"))
    assert response.status == 200, response.status
    assert "Title e1" in response.body
    assert f"{source.url}/entry/e1" in response.body
    assert detail.points(response.body, "views") == []


# Spec: | Metadata without chart | ... still render |
# Context: a v1 entry with one point per field renders its metadata too.
def test_v1_metadata_renders_without_a_chart(serve, make_vault, legacy, detail):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")],
                                 source_id="chan-1"))
    page = serve().client.get(detail.path("vault", "entries", "e1")).body
    assert "Title e1" in page
    assert "Description e1" in page
    assert "https://media.example.com/channel/chan-1/entry/e1" in page
