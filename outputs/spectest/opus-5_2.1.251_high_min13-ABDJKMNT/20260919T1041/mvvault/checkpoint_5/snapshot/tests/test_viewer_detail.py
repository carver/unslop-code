"""`/catalog/<name>/<category>/<id>` lookup rules, page content and source links."""

import json
import re

import pytest

from conftest import SOURCE_URL, V1_SOURCE_URL, v1_catalog, v1_entry, v2_catalog, v2_entry, v3_catalog, v3_entry

#: Two epoch keys whose numeric order is the reverse of their text order.
OLD_EPOCH, NEW_EPOCH = "999999999", "1718444400"
OLD_EPOCH_ISO, NEW_EPOCH_ISO = "2001-09-09T01:46:39", "2024-06-15T09:40:00"

#: Two ISO keys, oldest first.
OLD_ISO, NEW_ISO = "2024-01-01T00:00:00", "2024-06-15T09:40:00"


def detail(client, entry_id="a", name="v", category="episodes"):
    """The detail page body, asserting the route answered with one."""
    response = client.get(f"/catalog/{name}/{category}/{entry_id}")
    assert response.status_code == 200, response.status_code
    return response.text


def charts(html):
    """The chart payload embedded in a detail page, as plain data."""
    blocks = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.S)
    assert len(blocks) == 1, html
    return json.loads(blocks[0])


def points(html, field):
    """The `(timestamp, value)` pairs the page publishes for one field."""
    return [(point["timestamp"], point["value"]) for point in charts(html)[field]]


# Spec: `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for
# matching entry
def test_detail_route_answers_with_an_html_page(served):
    response = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])).get("/catalog/v/episodes/a")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]


# Spec: Category scope | Lookup occurs only inside named category
def test_lookup_is_scoped_to_the_named_category(served):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("a")], clips=[v3_entry("c")])
    client = served(catalog)
    assert client.get("/catalog/v/clips/a").status_code == 404
    assert client.get("/catalog/v/episodes/c").status_code == 404


# Spec: Cross-category duplicate IDs | Do not satisfy lookup
def test_a_duplicate_id_resolves_inside_its_own_category_only(served):
    catalog = v3_catalog(
        SOURCE_URL,
        episodes=[v3_entry("a", title={NEW_ISO: "episode side"})],
        clips=[v3_entry("a", title={NEW_ISO: "clip side"})],
    )
    client = served(catalog)
    assert "episode side" in detail(client, "a", category="episodes")
    assert "clip side" in detail(client, "a", category="clips")
    assert client.get("/catalog/v/streams/a").status_code == 404


# Spec: Removed entries (v3) | Remain accessible on detail page
def test_a_removed_entry_still_has_a_detail_page(served):
    entry = v3_entry("a", removed={OLD_ISO: False, NEW_ISO: True})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert "title-a" in body


# Spec: v1 lookup | Lookup in `entries` array when category is `entries`
def test_v1_detail_page_reads_the_entries_array(served):
    body = detail(served(v1_catalog([v1_entry("a")])), category="entries")
    assert "title-a" in body


# Spec: v2/v3 lookup | Lookup in matching category array
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
@pytest.mark.parametrize("build", [v2_catalog, v3_catalog])
def test_v2_and_v3_detail_pages_read_the_matching_category(served, build, category):
    entry = v2_entry("a") if build is v2_catalog else v3_entry("a")
    body = detail(served(build(SOURCE_URL, **{category: [entry]})), category=category)
    assert "title-a" in body


# Spec: Current title | Latest value from `title` history, resolved per version
# key format (v2/v3: lexicographic ISO keys)
def test_detail_page_shows_the_latest_title(served):
    entry = v3_entry("a", title={OLD_ISO: "old title", NEW_ISO: "new title"})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert "new title" in body
    assert "old title" not in body


# Spec: Current title ... resolved per version key format (v1: numeric epoch
# keys, whose text order is the reverse here)
def test_v1_detail_title_resolves_numerically(served):
    entry = v1_entry("a", title={OLD_EPOCH: "old title", NEW_EPOCH: "new title"})
    body = detail(served(v1_catalog([entry])), category="entries")
    assert "new title" in body
    assert "old title" not in body


# Spec: Current description | Latest value from `description` history, resolved
# per version key format
def test_detail_page_shows_the_latest_description(served):
    entry = v3_entry("a", description={OLD_ISO: "old words", NEW_ISO: "new words"})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert "new words" in body
    assert "old words" not in body


# Spec: Current description ... resolved per version key format (v1 numeric)
def test_v1_detail_description_resolves_numerically(served):
    entry = v1_entry("a", description={OLD_EPOCH: "old words", NEW_EPOCH: "new words"})
    body = detail(served(v1_catalog([entry])), category="entries")
    assert "new words" in body
    assert "old words" not in body


# Spec: Published date | Displayed
def test_detail_page_displays_the_published_date(served):
    entry = v3_entry("a", published="2023-11-02T07:15:00")
    assert "2023-11-02T07:15:00" in detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))


# Spec: Dimensions | Display width and height
def test_detail_page_displays_width_and_height(served):
    entry = v3_entry("a", width=640, height=360)
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert "640" in body
    assert "360" in body


# Spec: Back navigation | Link to current vault/category listing
def test_detail_page_links_back_to_the_category_listing(served):
    catalog = v3_catalog(SOURCE_URL, clips=[v3_entry("a")])
    assert 'href="/catalog/v/clips"' in detail(served(catalog), category="clips")


# Spec: Back navigation | Link to current vault/category listing (v1)
def test_v1_detail_page_links_back_to_entries(served):
    assert 'href="/catalog/v/entries"' in detail(served(v1_catalog([v1_entry("a")])), category="entries")


# Spec: Detail Page Source Link | v1 |
# `https://media.example.com/channel/<source_id>/entry/<id>`
def test_v1_source_link_is_derived_from_source_id(served):
    body = detail(served(v1_catalog([v1_entry("a")])), category="entries")
    assert f'href="{V1_SOURCE_URL}/entry/a"' in body


# Spec: Detail Page Source Link | v2 | `<source>/entry/<id>`
def test_v2_source_link_appends_to_the_stored_source(served):
    catalog = v2_catalog("https://media.example.com/channel/chan-9", episodes=[v2_entry("a")])
    assert 'href="https://media.example.com/channel/chan-9/entry/a"' in detail(served(catalog))


# Spec: Detail Page Source Link | v3 | `<source>/entry/<id>`
def test_v3_source_link_appends_to_the_stored_source(served):
    catalog = v3_catalog("https://media.example.com/channel/chan-9", episodes=[v3_entry("a")])
    assert 'href="https://media.example.com/channel/chan-9/entry/a"' in detail(served(catalog))


# Spec: Source link | Version-aware derivation; deterministic for same vault
# and entry
def test_source_link_is_stable_across_requests(served):
    client = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]))
    links = [re.findall(r'href="([^"]*?/entry/a)"', detail(client)) for _ in range(2)]
    assert links[0] == links[1] != []


# Spec: Media playback reference | Use media static endpoint when downloaded
# media file exists
def test_detail_page_references_the_media_endpoint(served):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])
    assert "/vault/v/media/a.mp4" in detail(served(catalog, media=["a.mp4"]))


# Spec: Downloaded media discovery | A downloaded media file counts as matching
# the entry when a saved filename in `<vault>/media/` contains the entry `id`;
# the detail page uses that exact filename in the media static endpoint URL
def test_detail_page_uses_the_exact_saved_filename(served):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])
    assert "/vault/v/media/prefix-a-suffix.webm" in detail(served(catalog, media=["prefix-a-suffix.webm"]))


# Spec: Downloaded media discovery ... contains the entry `id` (a file for a
# different entry is not a match)
def test_an_unrelated_media_file_is_not_referenced(served):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])
    assert "/vault/v/media/" not in detail(served(catalog, media=["b.mp4"]))


# Spec: Missing downloaded media | Keep metadata and chart data visible
def test_detail_page_without_media_keeps_metadata_and_chart_data(served):
    entry = v3_entry("a", views={OLD_ISO: 1, NEW_ISO: 5})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert "title-a" in body
    assert "description-a" in body
    assert "/vault/v/media/" not in body
    assert points(body, "views") == [(OLD_ISO, 1), (NEW_ISO, 5)]


# Spec: `views` and `likes` Chart Data | Fields exposed | `views`, `likes`
def test_chart_data_exposes_views_and_likes(served):
    entry = v3_entry("a", views={OLD_ISO: 1, NEW_ISO: 5}, likes={OLD_ISO: 2, NEW_ISO: 3})
    data = charts(detail(served(v3_catalog(SOURCE_URL, episodes=[entry]))))
    assert set(data) == {"views", "likes"}


# Spec: Embedding style | Machine-readable structured data embedded in HTML
def test_chart_data_is_embedded_as_parseable_data(served):
    entry = v3_entry("a", views={OLD_ISO: 1, NEW_ISO: 5})
    assert isinstance(charts(detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))), dict)


# Spec: Point payload | Preserve timestamp/value pairing
def test_chart_points_keep_their_timestamp_value_pairing(served):
    entry = v3_entry("a", views={OLD_ISO: 11, NEW_ISO: 22})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert points(body, "views") == [(OLD_ISO, 11), (NEW_ISO, 22)]


# Spec: Point payload | ... `likes` may use `null`; no filtering or replacement
def test_null_likes_are_preserved(served):
    entry = v3_entry("a", likes={OLD_ISO: None, NEW_ISO: 4})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert points(body, "likes") == [(OLD_ISO, None), (NEW_ISO, 4)]


# Spec: `likes` nulls | Preserved in chart data (a history of nothing but nulls
# keeps every point)
def test_an_all_null_likes_history_keeps_every_point(served):
    entry = v3_entry("a", likes={OLD_ISO: None, NEW_ISO: None})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert points(body, "likes") == [(OLD_ISO, None), (NEW_ISO, None)]


# Spec: Point order | Chronological, oldest first
def test_chart_points_are_chronological(served):
    entry = v3_entry("a", views={NEW_ISO: 5, OLD_ISO: 1})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert points(body, "views") == [(OLD_ISO, 1), (NEW_ISO, 5)]


# Spec: Single-point history | Chart for that field may be omitted
# Spec: Metadata without chart | Title, description, published date, dimensions,
# and source link still render
def test_a_single_point_history_still_renders_the_metadata(served):
    entry = v3_entry("a", views={NEW_ISO: 5})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert "title-a" in body
    assert "description-a" in body
    assert "2024-01-01T00:00:00" in body
    assert "1920" in body and "1080" in body
    assert f'href="{SOURCE_URL}/entry/a"' in body


# Spec: Single-point history | Chart for that field may be omitted (the drawn
# chart is left out; the data stays machine-readable)
def test_a_single_point_history_omits_the_drawn_chart(served):
    entry = v3_entry("a", views={NEW_ISO: 5}, likes={OLD_ISO: 1, NEW_ISO: 2})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert 'class="chart views"' not in body
    assert 'class="chart likes"' in body


# Spec: Chart Data | v1 | UNIX-epoch string keys | Convert to ISO 8601 UTC
def test_v1_chart_timestamps_are_converted_to_iso(served):
    entry = v1_entry("a", views={OLD_EPOCH: 1, NEW_EPOCH: 5})
    body = detail(served(v1_catalog([entry])), category="entries")
    assert points(body, "views") == [(OLD_EPOCH_ISO, 1), (NEW_EPOCH_ISO, 5)]


# Spec: Chart Data | v2 | ISO 8601 string | Pass through
def test_v2_chart_timestamps_pass_through(served):
    entry = v2_entry("a", views={OLD_ISO: 1, NEW_ISO: 5})
    body = detail(served(v2_catalog(SOURCE_URL, episodes=[entry])))
    assert points(body, "views") == [(OLD_ISO, 1), (NEW_ISO, 5)]


# Spec: Chart Data | v3 | ISO 8601 string | Pass through
def test_v3_chart_timestamps_pass_through(served):
    entry = v3_entry("a", views={OLD_ISO: 1, NEW_ISO: 5})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert points(body, "views") == [(OLD_ISO, 1), (NEW_ISO, 5)]


# Spec: v1 chart ordering | By numeric epoch value, not lexicographic
def test_v1_chart_ordering_is_numeric(served):
    entry = v1_entry("a", likes={NEW_EPOCH: 9, OLD_EPOCH: 1})
    body = detail(served(v1_catalog([entry])), category="entries")
    assert points(body, "likes") == [(OLD_EPOCH_ISO, 1), (NEW_EPOCH_ISO, 9)]


# Spec: Ordering Across Versions | v2/v3 | Lexicographic comparison of ISO 8601
# string keys
def test_v3_chart_ordering_is_lexicographic(served):
    entry = v3_entry("a", views={"2024-10-01T00:00:00": 3, "2024-02-01T00:00:00": 1})
    body = detail(served(v3_catalog(SOURCE_URL, episodes=[entry])))
    assert [point[0] for point in points(body, "views")] == ["2024-02-01T00:00:00", "2024-10-01T00:00:00"]


# Spec: Determinism | Chart point order | Chronological, oldest first (stable
# across repeated requests)
def test_chart_payload_is_identical_across_requests(served):
    entry = v3_entry("a", views={NEW_ISO: 5, OLD_ISO: 1}, likes={OLD_ISO: None, NEW_ISO: 4})
    client = served(v3_catalog(SOURCE_URL, episodes=[entry]))
    assert charts(detail(client)) == charts(detail(client))


# Spec: Detail pages and charts work on vaults of any supported version,
# normalizing across schema differences.
@pytest.mark.parametrize(
    "catalog, category",
    [
        (v1_catalog([v1_entry("a", views={OLD_EPOCH: 1, NEW_EPOCH: 5})]), "entries"),
        (v2_catalog(SOURCE_URL, episodes=[v2_entry("a", views={OLD_ISO: 1, NEW_ISO: 5})]), "episodes"),
        (v3_catalog(SOURCE_URL, episodes=[v3_entry("a", views={OLD_ISO: 1, NEW_ISO: 5})]), "episodes"),
    ],
)
def test_every_version_yields_iso_chart_timestamps(served, catalog, category):
    body = detail(served(catalog), category=category)
    stamps = [stamp for stamp, _ in points(body, "views")]
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", stamp) for stamp in stamps)
