"""Spec sections: `/catalog/<name>/<category>/<id>` Route, Lookup Rules, and
Page Content; Detail Page Source Link -- Version-Aware; `views` and `likes`
Chart Data; Chart Data -- Version-Aware Timestamp Normalization; Chart Data --
Ordering Across Versions; HTTP Error Handling; Determinism."""
import pytest

from conftest import (
    EPOCH_TO_ISO,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
)
from detailhelp import build_vault, chart_points, detail

REDIRECTS = (302, 303)

E1 = "2024-06-15T09:40:00"
E2 = "2024-07-01T12:00:00"
E3 = "2024-08-09T08:00:00"


@pytest.fixture
def v3_vault(tmp_path):
    return build_vault(tmp_path, v3_catalog(
        source="https://example.test/source.json",
        episodes=[v3_entry("e1"), v3_entry("e2")],
        streams=[v3_entry("s1")],
        clips=[v3_entry("c1")],
    ))


# ---------------------------------------------------------------------------
# `/catalog/<name>/<category>/<id>` Route
# ---------------------------------------------------------------------------

# --- Phrase: "| `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page
#     for matching entry |"
def test_detail_route_serves_html_for_a_matching_entry(viewer, v3_vault):
    response = detail(viewer(), "vault", "episodes", "e1")
    assert response.status == 200, response
    assert "text/html" in response.headers.get("Content-Type", ""), response
    assert "Title e1" in response.text, response


# --- Phrase: "Entry detail page" (context: a detail page, not the listing)
def test_detail_page_differs_from_the_category_listing(viewer, v3_vault):
    client = viewer()
    listing = client.get("/catalog/vault/episodes").text
    page = detail(client, "vault", "episodes", "e1").text
    assert page != listing, page


# ---------------------------------------------------------------------------
# `/catalog/<name>/<category>/<id>` Lookup Rules
# ---------------------------------------------------------------------------

# --- Phrase: "| Category scope | Lookup occurs only inside named category |"
def test_lookup_is_scoped_to_the_named_category(viewer, v3_vault):
    response = detail(viewer(), "vault", "episodes", "s1")
    assert response.status != 200 or "Title s1" not in response.text, response


def test_entry_is_found_in_its_own_category(viewer, v3_vault):
    response = detail(viewer(), "vault", "streams", "s1")
    assert response.status == 200, response
    assert "Title s1" in response.text, response


# --- Phrase: "| Cross-category duplicate IDs | Do not satisfy lookup |"
def test_duplicate_ids_across_categories_resolve_per_category(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(
        episodes=[v3_entry("dup", title={E1: "Episode copy"})],
        clips=[v3_entry("dup", title={E1: "Clip copy"})],
    ))
    client = viewer()
    episode = detail(client, "vault", "episodes", "dup")
    clip = detail(client, "vault", "clips", "dup")
    assert "Episode copy" in episode.text, episode
    assert "Clip copy" not in episode.text, episode
    assert "Clip copy" in clip.text, clip
    assert "Episode copy" not in clip.text, clip


def test_duplicate_id_in_another_category_does_not_satisfy_lookup(viewer,
                                                                  tmp_path):
    build_vault(tmp_path, v3_catalog(
        episodes=[v3_entry("e1")],
        clips=[v3_entry("only-clip")],
    ))
    response = detail(viewer(), "vault", "streams", "only-clip")
    assert response.status != 200 or "Title only-clip" not in response.text, (
        response)


# --- Phrase: "| Removed entries (v3) | Remain accessible on detail page |"
def test_removed_entry_is_still_reachable(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[
        v3_entry("gone", removed={E1: False, E2: True}),
    ]))
    response = detail(viewer(), "vault", "episodes", "gone")
    assert response.status == 200, response
    assert "Title gone" in response.text, response


# --- Phrase: "| v1 lookup | Lookup in `entries` array when category is
#     `entries` |"
def test_v1_detail_looks_up_the_entries_array(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry("e1"), v1_entry("e2")]))
    response = detail(viewer(), "vault", "entries", "e2")
    assert response.status == 200, response
    assert "Title e2" in response.text, response


# --- Phrase: "| v2/v3 lookup | Lookup in matching category array |"
@pytest.mark.parametrize("category,eid", [("episodes", "e1"),
                                          ("streams", "s1"),
                                          ("clips", "c1")])
def test_v3_detail_looks_up_the_matching_category(viewer, v3_vault, category,
                                                  eid):
    response = detail(viewer(), "vault", category, eid)
    assert response.status == 200, response
    assert "Title %s" % eid in response.text, response


def test_v2_detail_looks_up_the_matching_category(viewer, tmp_path):
    build_vault(tmp_path, v2_catalog(streams=[v2_entry("s9")]))
    response = detail(viewer(), "vault", "streams", "s9")
    assert response.status == 200, response
    assert "Title s9" in response.text, response


# ---------------------------------------------------------------------------
# `/catalog/<name>/<category>/<id>` Page Content
# ---------------------------------------------------------------------------

# --- Phrase: "| Current title | Latest value from `title` history, resolved
#     per version key format |"
def test_detail_shows_the_current_title(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[
        v3_entry("e1", title={E1: "Old title", E2: "New title"}),
    ]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "New title" in text, text
    assert "Old title" not in text, text


# --- Phrase: "| Current title | ... resolved per version key format |"
#     (context: Determinism -- "Current tracked value (v1) | Value at latest
#     key by numeric comparison")
def test_v1_detail_title_uses_numeric_key_comparison(viewer, tmp_path):
    # Lexicographically "999999999" sorts after "1000000000"; numerically it
    # is the older key, so the current title is the one at "1000000000".
    build_vault(tmp_path, v1_catalog(entries=[v1_entry(
        "e1",
        title={"999999999": "Older title", "1000000000": "Newer title"},
    )]))
    text = detail(viewer(), "vault", "entries", "e1").text
    assert "Newer title" in text, text
    assert "Older title" not in text, text


# --- Phrase: "| Current tracked value (v2/v3) | Value at latest key by
#     lexicographic comparison |"
@pytest.mark.parametrize("builder,entry_builder",
                         [(v2_catalog, v2_entry), (v3_catalog, v3_entry)])
def test_legacy_iso_detail_title_uses_lexicographic_comparison(
        viewer, tmp_path, builder, entry_builder):
    build_vault(tmp_path, builder(episodes=[entry_builder(
        "e1", title={E1: "Older title", E3: "Newer title"},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "Newer title" in text, text
    assert "Older title" not in text, text


# --- Phrase: "| Current description | Latest value from `description`
#     history, resolved per version key format |"
def test_detail_shows_the_current_description(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[
        v3_entry("e1", description={E1: "Old blurb", E2: "New blurb"}),
    ]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "New blurb" in text, text
    assert "Old blurb" not in text, text


def test_v1_detail_description_uses_numeric_key_comparison(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry(
        "e1",
        description={"999999999": "Old blurb", "1000000000": "New blurb"},
    )]))
    text = detail(viewer(), "vault", "entries", "e1").text
    assert "New blurb" in text, text
    assert "Old blurb" not in text, text


# --- Phrase: "| Published date | Displayed |"
def test_detail_shows_the_published_date(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[
        v3_entry("e1", published="2021-03-04T05:06:07"),
    ]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "2021-03-04" in text, text


def test_v1_detail_shows_the_published_date(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[
        v1_entry("e1", published="2019-12-31T23:59:59"),
    ]))
    text = detail(viewer(), "vault", "entries", "e1").text
    assert "2019-12-31" in text, text


# --- Phrase: "| Dimensions | Display width and height |"
def test_detail_shows_width_and_height(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[
        v3_entry("e1", width=640, height=360),
    ]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "640" in text, text
    assert "360" in text, text


def test_v1_detail_shows_width_and_height(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[
        v1_entry("e1", width=800, height=600),
    ]))
    text = detail(viewer(), "vault", "entries", "e1").text
    assert "800" in text, text
    assert "600" in text, text


# --- Phrase: "| Back navigation | Link to current vault/category listing |"
@pytest.mark.parametrize("category,eid", [("episodes", "e1"),
                                          ("streams", "s1")])
def test_detail_links_back_to_its_category_listing(viewer, v3_vault, category,
                                                   eid):
    text = detail(viewer(), "vault", category, eid).text
    assert '"/catalog/vault/%s"' % category in text, text


def test_v1_detail_links_back_to_the_entries_listing(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    text = detail(viewer(), "vault", "entries", "e1").text
    assert '"/catalog/vault/entries"' in text, text


# ---------------------------------------------------------------------------
# Detail Page Source Link -- Version-Aware
# ---------------------------------------------------------------------------

# --- Phrase: "| Source-platform link | Deterministic URL derived from vault
#     source information and entry `id` |" + "| v1 |
#     `https://media.example.com/channel/<source_id>/entry/<id>` |"
def test_v1_source_link_uses_the_legacy_channel_url(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(source_id="chan-77",
                                     entries=[v1_entry("e1")]))
    text = detail(viewer(), "vault", "entries", "e1").text
    assert ("https://media.example.com/channel/chan-77/entry/e1" in text), text


# --- Phrase: "| v2 | `<source>/entry/<id>` |"
def test_v2_source_link_appends_entry_to_the_source(viewer, tmp_path):
    build_vault(tmp_path, v2_catalog(source="https://host.test/feed.json",
                                     episodes=[v2_entry("e1")]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "https://host.test/feed.json/entry/e1" in text, text


# --- Phrase: "| v3 | `<source>/entry/<id>` |"
def test_v3_source_link_appends_entry_to_the_source(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(source="https://host.test/feed.json",
                                     clips=[v3_entry("c5")]))
    text = detail(viewer(), "vault", "clips", "c5").text
    assert "https://host.test/feed.json/entry/c5" in text, text


# --- Phrase: "| Source link | Version-aware derivation; deterministic for
#     same vault and entry |"
def test_source_link_is_stable_across_requests(viewer, v3_vault):
    client = viewer()
    first = detail(client, "vault", "episodes", "e1").text
    second = detail(client, "vault", "episodes", "e1").text
    assert first == second


# ---------------------------------------------------------------------------
# Detail page media reference
# ---------------------------------------------------------------------------

# --- Phrase: "| Media playback reference | Use media static endpoint when
#     downloaded media file exists |"
def test_detail_references_the_media_static_endpoint(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]),
                media=["e1.mp4"])
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "/vault/vault/media/e1.mp4" in text, text


# --- Phrase: "| Downloaded media discovery | A downloaded media file counts
#     as matching the entry when a saved filename in `<vault>/media/` contains
#     the entry `id`; the detail page uses that exact filename in the media
#     static endpoint URL |"
def test_detail_uses_the_exact_saved_media_filename(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]),
                media=["prefix-e1-suffix.mp4"])
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "/vault/vault/media/prefix-e1-suffix.mp4" in text, text


def test_detail_media_reference_is_absent_for_another_entrys_file(viewer,
                                                                 tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1"),
                                               v3_entry("e2")]),
                media=["e2.mp4"])
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "/vault/vault/media/" not in text, text


# --- Phrase: "| Missing downloaded media | Keep metadata and chart data
#     visible |"
def test_detail_without_media_keeps_metadata_and_chart_data(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1",
        published="2022-02-02T02:02:02",
        width=320, height=240,
        views={E1: 5, E2: 9},
        likes={E1: 1, E2: 2},
    )]))
    response = detail(viewer(), "vault", "episodes", "e1")
    assert response.status == 200, response
    text = response.text
    assert "Title e1" in text, text
    assert "2022-02-02" in text and "320" in text and "240" in text, text
    assert chart_points(text, "views") == [(E1, 5), (E2, 9)], text


# ---------------------------------------------------------------------------
# `views` and `likes` Chart Data
# ---------------------------------------------------------------------------

# --- Phrase: "| Fields exposed | `views`, `likes` |" + "| Embedding style |
#     Machine-readable structured data embedded in HTML |"
def test_views_and_likes_are_embedded_as_machine_readable_data(viewer,
                                                               tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1",
        views={E1: 10, E2: 20, E3: 30},
        likes={E1: 1, E2: 2, E3: 3},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert chart_points(text, "views") == [(E1, 10), (E2, 20), (E3, 30)], text
    assert chart_points(text, "likes") == [(E1, 1), (E2, 2), (E3, 3)], text


# --- Phrase: "| Point payload | Preserve timestamp/value pairing; ... no
#     filtering or replacement |"
def test_chart_points_preserve_timestamp_value_pairing(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1", views={E2: 777, E1: 111, E3: 999},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert chart_points(text, "views") == [(E1, 111), (E2, 777), (E3, 999)], (
        text)


# --- Phrase: "| Point payload | ... `likes` may use `null` ... |" +
#     "| `likes` nulls | Preserved in chart data |"
def test_null_likes_are_preserved(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1",
        views={E1: 10, E2: 20},
        likes={E1: None, E2: 4},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert chart_points(text, "likes") == [(E1, None), (E2, 4)], text


def test_an_all_null_likes_history_is_kept(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1",
        views={E1: 10, E2: 20},
        likes={E1: None, E2: None},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert chart_points(text, "likes") == [(E1, None), (E2, None)], text


# --- Phrase: "| Point order | Chronological, oldest first |"
def test_chart_points_are_chronological_oldest_first(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1", views={E3: 3, E1: 1, E2: 2},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    stamps = [stamp for stamp, _value in chart_points(text, "views")]
    assert stamps == [E1, E2, E3], text


# --- Phrase: "| Single-point history | Chart for that field may be omitted |"
def test_single_point_history_still_renders_a_page(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1", views={E1: 42}, likes={E1: 7},
    )]))
    response = detail(viewer(), "vault", "episodes", "e1")
    assert response.status == 200, response
    points = chart_points(response.text, "views")
    assert points is None or points == [(E1, 42)], response.text


# --- Phrase: "| Metadata without chart | Title, description, published date,
#     dimensions, and source link still render |"
def test_metadata_renders_when_history_has_a_single_point(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(
        source="https://host.test/feed.json",
        episodes=[v3_entry("e1", published="2020-01-02T03:04:05",
                           width=111, height=222,
                           views={E1: 42}, likes={E1: 7})],
    ))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert "Title e1" in text, text
    assert "Description e1" in text, text
    assert "2020-01-02" in text, text
    assert "111" in text and "222" in text, text
    assert "https://host.test/feed.json/entry/e1" in text, text


def test_metadata_renders_when_a_field_has_no_history(viewer, tmp_path):
    entry = v3_entry("e1", published="2020-01-02T03:04:05",
                     width=111, height=222)
    del entry["views"]
    del entry["likes"]
    build_vault(tmp_path, v3_catalog(source="https://host.test/feed.json",
                                     episodes=[entry]))
    response = detail(viewer(), "vault", "episodes", "e1")
    assert response.status == 200, response
    text = response.text
    assert "Title e1" in text and "Description e1" in text, text
    assert "2020-01-02" in text, text
    assert "111" in text and "222" in text, text
    assert "https://host.test/feed.json/entry/e1" in text, text


# ---------------------------------------------------------------------------
# Chart Data -- Version-Aware Timestamp Normalization
# ---------------------------------------------------------------------------

# --- Phrase: "| v1 | UNIX-epoch string (e.g., `"1718444400"`) | Convert to
#     ISO 8601 UTC |"
def test_v1_chart_timestamps_are_converted_to_iso_8601_utc(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry(
        "e1",
        views={"1718444400": 100, "1718448000": 150},
        likes={"1718444400": 5, "1718448000": 6},
    )]))
    text = detail(viewer(), "vault", "entries", "e1").text
    assert chart_points(text, "views") == [
        (EPOCH_TO_ISO["1718444400"], 100),
        (EPOCH_TO_ISO["1718448000"], 150),
    ], text


def test_v1_chart_timestamps_do_not_leak_epoch_keys(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry(
        "e1", views={"1718444400": 100, "1718448000": 150},
    )]))
    points = chart_points(detail(viewer(), "vault", "entries", "e1").text,
                          "views")
    assert [stamp for stamp, _v in points] == [
        EPOCH_TO_ISO["1718444400"], EPOCH_TO_ISO["1718448000"]], points


# --- Phrase: "| v2 | ISO 8601 string | Pass through |"
def test_v2_chart_timestamps_pass_through(viewer, tmp_path):
    build_vault(tmp_path, v2_catalog(episodes=[v2_entry(
        "e1", views={E1: 1, E2: 2},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert chart_points(text, "views") == [(E1, 1), (E2, 2)], text


# --- Phrase: "| v3 | ISO 8601 string | Pass through |"
def test_v3_chart_timestamps_pass_through(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1", views={E1: 1, E2: 2},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert chart_points(text, "views") == [(E1, 1), (E2, 2)], text


# --- Phrase: "Chart data must present timestamps in a **uniform format**
#     regardless of vault version. The output timestamp format for chart data
#     points is ISO 8601 (`YYYY-MM-DDTHH:MM:SS`)."
def test_chart_timestamp_format_is_uniform_across_versions(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry(
        "e1", views={"1718444400": 1, "1718448000": 2})]), name="one")
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1", views={EPOCH_TO_ISO["1718444400"]: 1,
                     EPOCH_TO_ISO["1718448000"]: 2})]), name="three")
    client = viewer()
    legacy = chart_points(detail(client, "one", "entries", "e1").text, "views")
    native = chart_points(detail(client, "three", "episodes", "e1").text,
                          "views")
    assert legacy == native, (legacy, native)


# ---------------------------------------------------------------------------
# Chart Data -- Ordering Across Versions
# ---------------------------------------------------------------------------

# --- Phrase: "| v1 | Numeric comparison of UNIX-epoch string keys |" +
#     "| v1 chart ordering | By numeric epoch value, not lexicographic |"
def test_v1_chart_order_is_numeric_not_lexicographic(viewer, tmp_path):
    # "999999999" is numerically older but lexicographically later than
    # "1000000000".
    build_vault(tmp_path, v1_catalog(entries=[v1_entry(
        "e1", views={"999999999": 11, "1000000000": 22},
    )]))
    text = detail(viewer(), "vault", "entries", "e1").text
    values = [value for _stamp, value in chart_points(text, "views")]
    assert values == [11, 22], text


def test_v1_chart_order_handles_the_zero_epoch(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry(
        "e1", views={"1718444400": 2, "0": 1},
    )]))
    text = detail(viewer(), "vault", "entries", "e1").text
    assert chart_points(text, "views") == [
        (EPOCH_TO_ISO["0"], 1),
        (EPOCH_TO_ISO["1718444400"], 2),
    ], text


# --- Phrase: "| v2 | Lexicographic comparison of ISO 8601 string keys |" and
#     "| v3 | Lexicographic comparison of ISO 8601 string keys |"
@pytest.mark.parametrize("builder,entry_builder",
                         [(v2_catalog, v2_entry), (v3_catalog, v3_entry)])
def test_iso_chart_order_is_lexicographic(viewer, tmp_path, builder,
                                          entry_builder):
    build_vault(tmp_path, builder(episodes=[entry_builder(
        "e1", views={E3: 3, E1: 1, E2: 2},
    )]))
    text = detail(viewer(), "vault", "episodes", "e1").text
    assert chart_points(text, "views") == [(E1, 1), (E2, 2), (E3, 3)], text


# --- Phrase: "| Chart point order | Chronological, oldest first |" (context:
#     Determinism -- repeated requests agree)
def test_chart_data_is_identical_across_requests(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[v3_entry(
        "e1", views={E2: 2, E1: 1, E3: 3}, likes={E1: None, E3: 9},
    )]))
    client = viewer()
    first = detail(client, "vault", "episodes", "e1").text
    second = detail(client, "vault", "episodes", "e1").text
    assert first == second


# ---------------------------------------------------------------------------
# HTTP Error Handling
# ---------------------------------------------------------------------------

# --- Phrase: "| Missing entry in specified category | HTTP `404`, or redirect
#     to category listing with error indication |"
def test_missing_entry_is_404_or_a_flagged_redirect(viewer, v3_vault):
    response = detail(viewer(), "vault", "episodes", "no-such-id")
    if response.status in REDIRECTS:
        assert response.location.startswith("/catalog/vault/episodes"), (
            response)
    else:
        assert response.status == 404, response


def test_missing_entry_response_is_well_formed(viewer, v3_vault):
    client = viewer()
    response = detail(client, "vault", "episodes", "no-such-id")
    assert response.status != 500, response
    assert "Traceback" not in response.text, response
    followed = client.get("/catalog/vault/episodes/no-such-id", follow=True)
    assert "no-such-id" in followed.text or followed.status == 404, followed


def test_missing_entry_in_a_v1_vault(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = detail(viewer(), "vault", "entries", "ghost")
    assert response.status != 500, response
    assert response.status == 404 or response.status in REDIRECTS, response


# --- Phrase: "| Non-existent vault on detail or static route | Redirect to
#     landing page with vault-not-found indication |"
def test_missing_vault_on_a_detail_route_redirects_to_the_landing_page(viewer):
    response = detail(viewer(), "ghost", "episodes", "e1")
    assert response.status in REDIRECTS, response
    assert not response.location.startswith("/catalog"), response


def test_missing_vault_landing_page_names_the_vault(viewer):
    client = viewer()
    response = client.get("/catalog/ghost/episodes/e1", follow=True)
    assert response.status == 200, response
    assert "ghost" in response.text, response
    assert "not found" in response.text.lower(), response


# --- Phrase: "| Invalid category on detail route | Same handling allowed for
#     invalid category listing route |"
@pytest.mark.parametrize("category", ["bogus", "entries"])
def test_invalid_category_on_a_v3_detail_route(viewer, v3_vault, category):
    response = detail(viewer(), "vault", category, "e1")
    assert response.status != 500, response
    if response.status in REDIRECTS:
        assert response.location.startswith("/catalog/vault/episodes"), response
    else:
        assert response.status in (400, 404), response


@pytest.mark.parametrize("category", ["episodes", "bogus"])
def test_invalid_category_on_a_v1_detail_route(viewer, tmp_path, category):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = detail(viewer(), "vault", category, "e1")
    assert response.status != 500, response
    if response.status in REDIRECTS:
        assert response.location.startswith("/catalog/vault/entries"), response
    else:
        assert response.status in (400, 404), response


# --- Phrase: "| Any HTTP error | Well-formed response; no raw stack trace or
#     internal detail exposure |"
@pytest.mark.parametrize("path", [
    "/catalog/vault/episodes/%2e%2e%2f%2e%2e%2fcatalog.json",
    "/catalog/vault/episodes/",
    "/catalog/vault/episodes/e1/extra",
])
def test_odd_detail_paths_stay_well_formed(viewer, v3_vault, path):
    response = viewer().get(path)
    assert response.status != 500, response
    assert "Traceback" not in response.text, response
    assert response.headers.get("Content-Type"), response


def test_detail_page_survives_a_malformed_entry(viewer, tmp_path):
    build_vault(tmp_path, v3_catalog(episodes=[
        {"id": "e1", "title": "not-a-history", "views": [1, 2]},
    ]))
    response = detail(viewer(), "vault", "episodes", "e1")
    assert response.status != 500, response
    assert "Traceback" not in response.text, response


def test_server_stays_up_after_a_bad_detail_request(viewer, v3_vault):
    client = viewer()
    client.get("/catalog/vault/episodes/nope")
    client.get("/catalog/ghost/episodes/e1")
    assert detail(client, "vault", "episodes", "e1").status == 200
