"""Spec: the `views` and `likes` chart-data tables, including version-aware
timestamp normalization and ordering."""
import pytest

from digest_helpers import (E1, E2, E3, K1, K2, K3, legacy_entry, v1, v1_entry,
                            v2, v3, v3_entry)
from viewer_helpers import (ISO_RE, chart_points, chart_timestamps,
                            chart_values, json_blobs, text_of)

# E1/E2/E3 are the UNIX-epoch twins of the ISO keys K1/K2/K3:
# 1704067200 == 2024-01-01T00:00:00Z, and so on.


def detail(server, name="vault", category="episodes", entry_id="e1"):
    return server.get("/catalog/%s/%s/%s" % (name, category, entry_id))


# --------------------------------------------------------------------------
# Chart data table
# --------------------------------------------------------------------------
# Spec: "| Fields exposed | `views`, `likes` |"
def test_views_and_likes_are_exposed(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", views={K1: 10, K2: 20},
                                     likes={K1: 1, K2: 2})]))
    body = detail(serve()).body
    assert chart_points(body, "views") is not None
    assert chart_points(body, "likes") is not None


# Spec: "| Embedding style | Machine-readable structured data embedded in HTML |"
def test_chart_data_is_machine_readable(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", views={K1: 10, K2: 20})]))
    blobs = json_blobs(detail(serve()).body)
    assert blobs, "no machine-readable payload embedded in the page"


# Spec: "| Point payload | Preserve timestamp/value pairing ... |"
def test_points_preserve_timestamp_value_pairing(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     views={K1: 10, K2: 20, K3: 30})]))
    points = chart_points(detail(serve()).body, "views")
    assert points == [(K1, 10), (K2, 20), (K3, 30)]


# Spec: "| Point payload | ... `likes` may use `null` ... |" +
# "| `likes` nulls | Preserved in chart data |"
def test_null_likes_are_preserved(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     likes={K1: 1, K2: None, K3: 3})]))
    assert chart_values(detail(serve()).body, "likes") == [1, None, 3]


# Spec: "| Point payload | ... no filtering or replacement |" -- every point
# in the history reaches the payload, duplicates of a value included.
def test_no_points_are_filtered_out(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     views={K1: 7, K2: 7, K3: 7})]))
    assert chart_values(detail(serve()).body, "views") == [7, 7, 7]


# Spec: "| Point payload | ... no filtering or replacement |" -- a `null` is
# not replaced with a zero or dropped, even at the end of the history.
def test_trailing_null_is_neither_dropped_nor_replaced(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", likes={K1: 5, K2: None})]))
    assert chart_values(detail(serve()).body, "likes") == [5, None]


# Spec: "| Point order | Chronological, oldest first |"
def test_points_are_chronological_oldest_first(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     views={K3: 30, K1: 10, K2: 20})]))
    assert chart_timestamps(detail(serve()).body, "views") == [K1, K2, K3]


# Spec: "| Single-point history | Chart for that field may be omitted |" +
# "| Metadata without chart | Title, description, published date, dimensions,
# and source link still render |"
def test_single_point_history_still_renders_metadata(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Solo", key=K1)]))
    response = detail(serve())
    assert response.status == 200, response
    text = text_of(response.body)
    assert "Solo" in text
    assert "Desc" in text
    assert "2024-05-01" in text
    assert "1920" in text and "1080" in text
    from viewer_helpers import hrefs
    assert "https://media.example.com/channel/chan42/entry/e1" in \
        hrefs(response.body)


# Spec: "| Metadata without chart | ... |" -- an entry with no `views`/`likes`
# history at all is still a complete page.
def test_entry_without_history_still_renders_metadata(serve, make_vault):
    entry = v3_entry(id="e1", title="Bare")
    entry["views"] = {}
    entry["likes"] = {}
    make_vault(v3(episodes=[entry]))
    response = detail(serve())
    assert response.status == 200, response
    text = text_of(response.body)
    assert "Bare" in text
    assert "2024-05-01" in text


# --------------------------------------------------------------------------
# Version-aware timestamp normalization
# --------------------------------------------------------------------------
# Spec: "| v1 | UNIX-epoch string (e.g., `\"1718444400\"`) | Convert to ISO 8601
# UTC |"
def test_v1_epoch_keys_become_iso_timestamps(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", views={E1: 10, E2: 20})]))
    body = serve().get("/catalog/vault/entries/e1").body
    assert chart_timestamps(body, "views") == [K1, K2]


# Spec: "The output timestamp format for chart data points is ISO 8601
# (`YYYY-MM-DDTHH:MM:SS`)."
@pytest.mark.parametrize("catalog,category", [
    (v1(entries=[v1_entry(id="e1", views={E1: 10, E2: 20})]), "entries"),
    (v2(episodes=[legacy_entry(id="e1", views={K1: 10, K2: 20})]), "episodes"),
    (v3(episodes=[v3_entry(id="e1", views={K1: 10, K2: 20})]), "episodes"),
])
def test_chart_timestamps_are_iso_8601_for_every_version(serve, make_vault,
                                                         catalog, category):
    make_vault(catalog)
    body = serve().get("/catalog/vault/%s/e1" % category).body
    stamps = chart_timestamps(body, "views")
    assert stamps, body
    for stamp in stamps:
        assert ISO_RE.match(str(stamp)), stamp


# Spec: "| v1 | ... | Convert to ISO 8601 UTC |" -- the raw epoch string does
# not survive into the payload.
def test_v1_raw_epoch_string_is_not_emitted(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", views={E1: 10, E2: 20})]))
    body = serve().get("/catalog/vault/entries/e1").body
    assert E1 not in str(chart_points(body, "views"))


# Spec: "| v2 | ISO 8601 string | Pass through |"
def test_v2_iso_keys_pass_through(serve, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1", views={K1: 10, K2: 20})]))
    assert chart_timestamps(detail(serve()).body, "views") == [K1, K2]


# Spec: "| v3 | ISO 8601 string | Pass through |"
def test_v3_iso_keys_pass_through(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", views={K1: 10, K2: 20})]))
    assert chart_timestamps(detail(serve()).body, "views") == [K1, K2]


# Spec: "Chart data must present timestamps in a **uniform format** regardless
# of vault version." -- the same instants render identically across versions.
def test_same_instants_render_identically_across_versions(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", views={E1: 10, E2: 20})]),
               name="one")
    make_vault(v3(episodes=[v3_entry(id="e1", views={K1: 10, K2: 20})]),
               name="three")
    server = serve()
    old = chart_points(server.get("/catalog/one/entries/e1").body, "views")
    new = chart_points(server.get("/catalog/three/episodes/e1").body, "views")
    assert old == new


# --------------------------------------------------------------------------
# Ordering across versions
# --------------------------------------------------------------------------
# Spec: "| v1 | Numeric comparison of UNIX-epoch string keys |" +
# "| v1 chart ordering | By numeric epoch value, not lexicographic |" --
# "999999999" sorts before "1000000000" numerically but after it as text.
def test_v1_ordering_is_numeric_not_lexicographic(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", views={"1000000000": 20,
                                                    "999999999": 10})]))
    body = serve().get("/catalog/vault/entries/e1").body
    assert chart_values(body, "views") == [10, 20]
    stamps = chart_timestamps(body, "views")
    assert stamps == sorted(stamps)


# Spec: "| v2 | Lexicographic comparison of ISO 8601 string keys |"
def test_v2_ordering_is_lexicographic(serve, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1",
                                         views={K3: 30, K1: 10, K2: 20})]))
    assert chart_values(detail(serve()).body, "views") == [10, 20, 30]


# Spec: "| v3 | Lexicographic comparison of ISO 8601 string keys |"
def test_v3_ordering_is_lexicographic(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     views={K2: 20, K3: 30, K1: 10})]))
    assert chart_values(detail(serve()).body, "views") == [10, 20, 30]


# Spec: "| Chart point order | Chronological, oldest first |" -- `likes` is
# ordered on the same rule as `views`.
def test_likes_share_the_chronological_order(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     likes={K3: 3, K1: 1, K2: None})]))
    body = detail(serve()).body
    assert chart_timestamps(body, "likes") == [K1, K2, K3]
    assert chart_values(body, "likes") == [1, None, 3]


# Spec: "| Chart output timestamps | Always ISO 8601 regardless of vault
# version |" -- and the whole payload is stable across repeated requests.
def test_chart_payload_is_deterministic(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", views={E3: 30, E1: 10, E2: 20})]))
    server = serve()
    bodies = [server.get("/catalog/vault/entries/e1").body for _ in range(3)]
    assert bodies[0] == bodies[1] == bodies[2]
    assert chart_timestamps(bodies[0], "views") == [K1, K2, K3]
