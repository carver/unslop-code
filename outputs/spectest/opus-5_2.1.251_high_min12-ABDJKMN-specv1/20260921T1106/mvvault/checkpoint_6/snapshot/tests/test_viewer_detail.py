"""Spec sections: `/catalog/<name>/<category>/<id>` Route / Lookup Rules /
Page Content / Detail Page Source Link — Version-Aware / `views` and `likes`
Chart Data / Chart Data — Version-Aware Timestamp Normalization / Chart Data —
Ordering Across Versions / HTTP Error Handling / Determinism."""
import json
import re

import pytest
from conftest import make_vault, place_file, v1_entry, v2_entry, v3_entry

REDIRECTS = (302, 303)

T1 = "2024-01-01T00:00:00"
T2 = "2024-02-01T00:00:00"
T3 = "2024-03-01T00:00:00"

# Numeric and lexicographic order disagree for this pair: numerically
# 1000000000 > 999999999, lexicographically "999999999" > "1000000000".
EPOCH_SMALL = "999999999"
EPOCH_SMALL_ISO = "2001-09-09T01:46:39"
EPOCH_BIG = "1000000000"
EPOCH_BIG_ISO = "2001-09-09T01:46:40"

V2_SOURCE = "http://example.invalid/f.json"


# --------------------------------------------------------------------------
# vault fixtures
# --------------------------------------------------------------------------

def v1_vault(tmp_path, entries=(), name="v", source_id="chan42"):
    return make_vault(tmp_path, name, {"version": 1, "source_id": source_id,
                                       "entries": list(entries)})


def v2_vault(tmp_path, episodes=(), streams=(), clips=(), name="v",
             source=V2_SOURCE):
    return make_vault(tmp_path, name,
                      {"version": 2, "source": source,
                       "episodes": list(episodes), "streams": list(streams),
                       "clips": list(clips)})


def v3_vault(tmp_path, episodes=(), streams=(), clips=(), name="v",
             source=V2_SOURCE):
    catalog = {"version": 3, "source": source, "episodes": list(episodes),
               "streams": list(streams), "clips": list(clips)}
    return make_vault(tmp_path, name, catalog)


def detail(name, category, eid):
    return "/catalog/%s/%s/%s" % (name, category, eid)


def unescape(text):
    return (text.replace("&quot;", '"').replace("&#39;", "'")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&amp;", "&"))


def page_text(page):
    return unescape(page.body)


def links(page):
    return [unescape(href) for href in page.links()]


def has_link(page, href):
    return any(link.split("?")[0].rstrip("/") == href.rstrip("/")
               for link in links(page))


def detail_page(viewer, tmp_path, name, category, eid):
    page = viewer().browser().get(detail(name, category, eid))
    assert page.status == 200, (page.status, page.body[:300])
    return page


# --------------------------------------------------------------------------
# machine-readable chart payload extraction
#
# The spec leaves the container and key names unspecified, so these helpers
# accept any JSON embedded in the page that exposes `views` / `likes` lists of
# timestamp/value points (points may be two-element arrays or small objects).
# --------------------------------------------------------------------------

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
JSON_SCRIPT = re.compile(
    r'<script[^>]*type\s*=\s*"application/(?:ld\+)?json"[^>]*>(.*?)</script>',
    re.S | re.I)


def json_blocks(body):
    """Every embedded JSON payload on the page that actually parses."""
    blocks = []
    for raw in JSON_SCRIPT.findall(body):
        try:
            blocks.append(json.loads(unescape(raw).strip()))
        except ValueError:
            continue
    return blocks


def walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def point_pair(point):
    """(timestamp, value) from one payload point, whatever shape it has."""
    if isinstance(point, (list, tuple)) and len(point) == 2:
        first, second = point
        if isinstance(second, str) and ISO.match(second):
            return second, first
        return first, second
    if isinstance(point, dict) and len(point) == 2:
        stamps = [value for value in point.values()
                  if isinstance(value, str) and ISO.match(value)]
        others = [value for value in point.values()
                  if not (isinstance(value, str) and ISO.match(value))]
        if len(stamps) == 1 and len(others) == 1:
            return stamps[0], others[0]
    raise AssertionError("unrecognized chart point: %r" % (point,))


def series(page, field):
    """The chart points for `field`, or None when the page embeds none."""
    for block in json_blocks(page.body):
        for node in walk(block):
            if isinstance(node, dict) and isinstance(node.get(field), list):
                return [point_pair(point) for point in node[field]]
    return None


def stamps(page, field):
    return [stamp for stamp, _ in series(page, field)]


def values(page, field):
    return [value for _, value in series(page, field)]


def history(pairs):
    return dict(pairs)


# --------------------------------------------------------------------------
# `/catalog/<name>/<category>/<id>` Route
# --------------------------------------------------------------------------

# Phrase: "`GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for
#          matching entry"
def test_detail_route_returns_html_for_matching_entry(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", title="Alpha")])
    page = viewer().browser().get(detail("v", "episodes", "e1"))
    assert page.status == 200
    assert "text/html" in (page.header("Content-Type") or "")
    assert "Alpha" in page_text(page)


# Phrase: "Entry detail page for matching entry"
# Context: the detail page is about one entry, not the whole category listing.
def test_detail_page_does_not_list_the_other_entries(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", title="Alpha"),
                                 v3_entry("e2", title="Beta")])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "Alpha" in page_text(page)
    assert not has_link(page, detail("v", "episodes", "e2")), page.body


# --------------------------------------------------------------------------
# `/catalog/<name>/<category>/<id>` Lookup Rules
# --------------------------------------------------------------------------

# Phrase: "Category scope | Lookup occurs only inside named category"
def test_lookup_is_limited_to_the_named_category(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")], streams=[v3_entry("s1")])
    page = viewer().browser().get(detail("v", "episodes", "s1"))
    assert page.status != 200, page.body[:300]


# Phrase: "Cross-category duplicate IDs | Do not satisfy lookup"
# Context: the same id in two categories resolves to the entry that actually
# lives in the requested category.
def test_duplicate_ids_resolve_within_their_own_category(viewer, tmp_path):
    v3_vault(tmp_path,
             episodes=[v3_entry("dup", title="EpisodeOne")],
             streams=[v3_entry("dup", title="StreamOne")])
    browser = viewer().browser()
    episode = browser.get(detail("v", "episodes", "dup"))
    stream = browser.get(detail("v", "streams", "dup"))
    assert "EpisodeOne" in page_text(episode)
    assert "StreamOne" not in page_text(episode)
    assert "StreamOne" in page_text(stream)
    assert "EpisodeOne" not in page_text(stream)


# Phrase: "Cross-category duplicate IDs | Do not satisfy lookup"
# Context: an id present only in `clips` is not found under `episodes`.
def test_id_from_another_category_is_not_found(viewer, tmp_path):
    v3_vault(tmp_path, clips=[v3_entry("c1", title="Clipped")])
    page = viewer().browser().get(detail("v", "episodes", "c1"))
    assert page.status != 200
    assert "Clipped" not in page_text(page)


# Phrase: "Removed entries (v3) | Remain accessible on detail page"
def test_removed_entry_still_has_a_detail_page(viewer, tmp_path):
    entry = v3_entry("e1", title="Gone", removed=True)
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "Gone" in page_text(page)


# Phrase: "Removed entries (v3) | Remain accessible on detail page"
# Context: a removal recorded after the entry existed keeps its metadata.
def test_removed_entry_keeps_metadata_and_charts(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, title="Gone", views=5)
    entry["views"][T2] = 9
    entry["likes"][T2] = 3
    entry["removed"] = {T1: False, T2: True}
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert values(page, "views") == [5, 9]


# Phrase: "v1 lookup | Lookup in `entries` array when category is `entries`"
def test_v1_detail_page_uses_the_entries_array(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1", title="Solo")])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert "Solo" in page_text(page)


# Phrase: "v1 lookup | Lookup in `entries` array when category is `entries`"
# Context: an id that is not in the v1 array is not found.
def test_v1_unknown_id_is_not_found(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    page = viewer().browser().get(detail("v", "entries", "nope"))
    assert page.status != 200


# Phrase: "v2/v3 lookup | Lookup in matching category array"
@pytest.mark.parametrize("category,eid", [("episodes", "e1"), ("streams", "s1"),
                                          ("clips", "c1")])
def test_v3_detail_page_per_category(viewer, tmp_path, category, eid):
    v3_vault(tmp_path, episodes=[v3_entry("e1", title="E")],
             streams=[v3_entry("s1", title="S")],
             clips=[v3_entry("c1", title="C")])
    page = detail_page(viewer, tmp_path, "v", category, eid)
    assert category[0].upper() in page_text(page)


# Phrase: "v2/v3 lookup | Lookup in matching category array"
@pytest.mark.parametrize("category,eid", [("episodes", "e1"), ("streams", "s1"),
                                          ("clips", "c1")])
def test_v2_detail_page_per_category(viewer, tmp_path, category, eid):
    v2_vault(tmp_path, episodes=[v2_entry("e1", title="E")],
             streams=[v2_entry("s1", title="S")],
             clips=[v2_entry("c1", title="C")])
    page = detail_page(viewer, tmp_path, "v", category, eid)
    assert page.status == 200


# --------------------------------------------------------------------------
# `/catalog/<name>/<category>/<id>` Page Content
# --------------------------------------------------------------------------

# Phrase: "Current title | Latest value from `title` history, resolved per
#          version key format"
def test_v3_title_is_the_latest_iso_key(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, title="Old")
    entry["title"][T2] = "New"
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "New" in page_text(page)
    assert "Old" not in page_text(page)


# Phrase: "Current title | ... resolved per version key format"
# Context: v2 keys are ISO strings and compare lexicographically.
def test_v2_title_is_the_latest_iso_key(viewer, tmp_path):
    entry = v2_entry("e1", stamp=T2, title="New")
    entry["title"][T1] = "Old"
    v2_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "New" in page_text(page)
    assert "Old" not in page_text(page)


# Phrase: "Current tracked value (v1) | Value at latest key by numeric
#          comparison"
def test_v1_title_is_the_latest_by_numeric_epoch(viewer, tmp_path):
    entry = v1_entry("e1", epoch=EPOCH_SMALL, title="Old")
    entry["title"][EPOCH_BIG] = "New"
    v1_vault(tmp_path, [entry])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert "New" in page_text(page)
    assert "Old" not in page_text(page)


# Phrase: "Current description | Latest value from `description` history,
#          resolved per version key format"
def test_v3_description_is_the_latest_value(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, description="Older text")
    entry["description"][T2] = "Newer text"
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "Newer text" in page_text(page)
    assert "Older text" not in page_text(page)


# Phrase: "Current description | ... resolved per version key format"
# Context: v1 description history is keyed by epoch strings.
def test_v1_description_is_the_latest_by_numeric_epoch(viewer, tmp_path):
    entry = v1_entry("e1", epoch=EPOCH_SMALL, description="Older text")
    entry["description"][EPOCH_BIG] = "Newer text"
    v1_vault(tmp_path, [entry])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert "Newer text" in page_text(page)
    assert "Older text" not in page_text(page)


# Phrase: "Published date | Displayed"
def test_published_date_is_displayed(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", published="2023-07-04T12:30:00")])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "2023-07-04" in page_text(page)


# Phrase: "Published date | Displayed"
# Context: v1 entries carry the same static `published` field.
def test_v1_published_date_is_displayed(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1", published="2022-05-06T01:02:03")])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert "2022-05-06" in page_text(page)


# Phrase: "Dimensions | Display width and height"
def test_dimensions_are_displayed(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", width=1280, height=720)])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    text = page_text(page)
    assert "1280" in text and "720" in text


# Phrase: "Dimensions | Display width and height"
# Context: v1 stores the same static dimensions.
def test_v1_dimensions_are_displayed(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1", width=640, height=480)])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    text = page_text(page)
    assert "640" in text and "480" in text


# Phrase: "Back navigation | Link to current vault/category listing"
def test_back_link_points_at_the_category_listing(viewer, tmp_path):
    v3_vault(tmp_path, streams=[v3_entry("s1")])
    page = detail_page(viewer, tmp_path, "v", "streams", "s1")
    assert has_link(page, "/catalog/v/streams"), links(page)


# Phrase: "Back navigation | Link to current vault/category listing"
# Context: a v1 vault's listing lives under `entries`.
def test_v1_back_link_points_at_entries(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert has_link(page, "/catalog/v/entries"), links(page)


# --------------------------------------------------------------------------
# Detail Page Source Link — Version-Aware
# --------------------------------------------------------------------------

# Phrase: "v1 | `https://media.example.com/channel/<source_id>/entry/<id>`"
def test_v1_source_link(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")], source_id="chan42")
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert "https://media.example.com/channel/chan42/entry/e1" in \
        page_text(page), page.body


# Phrase: "v1 | `https://media.example.com/channel/<source_id>/entry/<id>`"
# Context: the link tracks the vault's own `source_id`.
def test_v1_source_link_uses_the_stored_source_id(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e9")], source_id="other")
    page = detail_page(viewer, tmp_path, "v", "entries", "e9")
    assert "https://media.example.com/channel/other/entry/e9" in page_text(page)


# Phrase: "v2 | `<source>/entry/<id>`"
def test_v2_source_link(viewer, tmp_path):
    v2_vault(tmp_path, episodes=[v2_entry("e1")],
             source="http://example.invalid/feed.json")
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "http://example.invalid/feed.json/entry/e1" in page_text(page)


# Phrase: "v3 | `<source>/entry/<id>`"
def test_v3_source_link(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")],
             source="http://example.invalid/feed.json")
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "http://example.invalid/feed.json/entry/e1" in page_text(page)


# Phrase: "Source link | Version-aware derivation; deterministic for same vault
#          and entry"
def test_source_link_is_stable_across_requests(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    browser = viewer().browser()
    first = browser.get(detail("v", "episodes", "e1")).body
    second = browser.get(detail("v", "episodes", "e1")).body
    assert first == second


# --------------------------------------------------------------------------
# Media playback reference / downloaded media discovery
# --------------------------------------------------------------------------

# Phrase: "Media playback reference | Use media static endpoint when downloaded
#          media file exists"
def test_media_reference_uses_the_static_endpoint(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", "e1.mp4", b"DATA")
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "/vault/v/media/e1.mp4" in page_text(page), page.body


# Phrase: "Downloaded media discovery | A downloaded media file counts as
#          matching the entry when a saved filename in `<vault>/media/`
#          contains the entry `id`"
def test_media_match_is_by_filename_containing_the_id(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", "prefix-e1-suffix.webm", b"DATA")
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "/vault/v/media/prefix-e1-suffix.webm" in page_text(page), page.body


# Phrase: "the detail page uses that exact filename in the media static
#          endpoint URL"
def test_media_reference_uses_the_exact_saved_filename(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", "e1.custom.ext", b"DATA")
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "/vault/v/media/e1.custom.ext" in page_text(page), page.body


# Phrase: "Media playback reference | Use media static endpoint when downloaded
#          media file exists"
# Context: the referenced URL actually serves the stored bytes.
def test_media_reference_is_fetchable(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_file(vault, "media", "e1.mp4", b"DATA")
    browser = viewer().browser()
    page = browser.get(detail("v", "episodes", "e1"))
    found = [link for link in links(page) if "/vault/v/media/" in link]
    assert found, page.body
    served = browser.get(found[0]) if found[0].startswith("/") else None
    if served is not None:
        assert served.status == 200


# Phrase: "Downloaded media discovery"
# Context: a v1 vault resolves downloaded media the same way.
def test_v1_media_reference_uses_the_static_endpoint(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    place_file(vault, "media", "e1.mp4", b"DATA")
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert "/vault/v/media/e1.mp4" in page_text(page)


# Phrase: "Missing downloaded media | Keep metadata and chart data visible"
def test_missing_media_keeps_metadata_and_charts(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, title="Alpha", views=5,
                     published="2023-07-04T12:30:00", width=1280, height=720)
    entry["views"][T2] = 9
    entry["likes"][T2] = 4
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    text = page_text(page)
    assert "Alpha" in text
    assert "2023-07-04" in text
    assert "1280" in text and "720" in text
    assert values(page, "views") == [5, 9]


# Phrase: "Missing downloaded media"
# Context: no media file means no media static URL is referenced.
def test_missing_media_does_not_reference_the_media_endpoint(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "/vault/v/media/" not in page_text(page), page.body


# Phrase: "Missing downloaded media"
# Context: a media file for another entry does not count as this entry's.
def test_other_entrys_media_is_not_referenced(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])
    place_file(vault, "media", "e2.mp4", b"DATA")
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert "/vault/v/media/e2.mp4" not in page_text(page)


# --------------------------------------------------------------------------
# `views` and `likes` Chart Data
# --------------------------------------------------------------------------

# Phrase: "Fields exposed | `views`, `likes`"
def test_views_and_likes_are_both_exposed(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, views=5, likes=1)
    entry["views"][T2] = 9
    entry["likes"][T2] = 3
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert values(page, "views") == [5, 9]
    assert values(page, "likes") == [1, 3]


# Phrase: "Embedding style | Machine-readable structured data embedded in HTML"
def test_chart_data_is_embedded_machine_readable_json(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, views=5)
    entry["views"][T2] = 9
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert json_blocks(page.body), page.body
    assert series(page, "views") is not None


# Phrase: "Point payload | Preserve timestamp/value pairing"
def test_points_keep_their_timestamp_value_pairing(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, views=5)
    entry["views"][T2] = 9
    entry["views"][T3] = 11
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert history(series(page, "views")) == {T1: 5, T2: 9, T3: 11}


# Phrase: "Point payload | ... `likes` may use `null`; no filtering or
#          replacement"
def test_null_likes_are_preserved(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, likes=None)
    entry["likes"][T2] = 4
    entry["likes"][T3] = None
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert values(page, "likes") == [None, 4, None]


# Phrase: "no filtering or replacement"
# Context: zeros and repeated values survive into the payload unchanged.
def test_zero_and_repeated_values_are_not_filtered(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, views=0)
    entry["views"][T2] = 0
    entry["views"][T3] = 7
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert values(page, "views") == [0, 0, 7]


# Phrase: "Point order | Chronological, oldest first"
def test_points_are_oldest_first(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T3, views=11)
    entry["views"][T1] = 5
    entry["views"][T2] = 9
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert stamps(page, "views") == [T1, T2, T3]
    assert values(page, "views") == [5, 9, 11]


# Phrase: "Point order | Chronological, oldest first"
# Context: `likes` is ordered the same way as `views`.
def test_likes_points_are_oldest_first(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T3, likes=3)
    entry["likes"][T1] = 1
    entry["likes"][T2] = 2
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert values(page, "likes") == [1, 2, 3]


# Phrase: "Single-point history | Chart for that field may be omitted"
# Context: either the field is absent from the payload, or it holds that one
# point; nothing else is conforming.
def test_single_point_history_is_omitted_or_single(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", stamp=T1, views=5)])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    points = series(page, "views")
    assert points is None or points == [(T1, 5)]


# Phrase: "Metadata without chart | Title, description, published date,
#          dimensions, and source link still render"
def test_metadata_renders_without_a_chart(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1", stamp=T1, title="Alpha",
                                          description="Desc",
                                          published="2023-07-04T12:30:00",
                                          width=1280, height=720)])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    text = page_text(page)
    assert "Alpha" in text
    assert "Desc" in text
    assert "2023-07-04" in text
    assert "1280" in text and "720" in text
    assert "/entry/e1" in text


# --------------------------------------------------------------------------
# Chart Data — Version-Aware Timestamp Normalization
# --------------------------------------------------------------------------

# Phrase: "v1 | UNIX-epoch string (e.g., `\"1718444400\"`) | Convert to ISO 8601
#          UTC"
def test_v1_epoch_keys_become_iso_timestamps(viewer, tmp_path):
    entry = v1_entry("e1", epoch="1718444400", views=5)
    entry["views"]["1718530800"] = 9
    v1_vault(tmp_path, [entry])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert stamps(page, "views") == ["2024-06-15T09:40:00",
                                     "2024-06-16T09:40:00"]


# Phrase: "The output timestamp format for chart data points is ISO 8601
#          (`YYYY-MM-DDTHH:MM:SS`)."
def test_v1_chart_timestamps_match_the_iso_shape(viewer, tmp_path):
    entry = v1_entry("e1", epoch=EPOCH_SMALL, views=5)
    entry["views"][EPOCH_BIG] = 9
    v1_vault(tmp_path, [entry])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    for stamp in stamps(page, "views"):
        assert ISO.match(stamp), stamp


# Phrase: "v2 | ISO 8601 string | Pass through"
def test_v2_timestamps_pass_through(viewer, tmp_path):
    entry = v2_entry("e1", stamp=T1, views=5)
    entry["views"][T2] = 9
    v2_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert stamps(page, "views") == [T1, T2]


# Phrase: "v3 | ISO 8601 string | Pass through"
def test_v3_timestamps_pass_through(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T1, views=5)
    entry["views"][T2] = 9
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert stamps(page, "views") == [T1, T2]


# Phrase: "Chart data must present timestamps in a uniform format regardless of
#          vault version."
# Context: the same moment reaches the chart identically from v1 and from v3.
def test_v1_and_v3_agree_on_the_same_moment(viewer, tmp_path):
    v1_entry_data = v1_entry("e1", epoch="1718444400", views=5)
    v1_entry_data["views"]["1718530800"] = 9
    v1_vault(tmp_path, [v1_entry_data], name="one")
    v3_entry_data = v3_entry("e1", stamp="2024-06-15T09:40:00", views=5)
    v3_entry_data["views"]["2024-06-16T09:40:00"] = 9
    v3_vault(tmp_path, episodes=[v3_entry_data], name="three")
    browser = viewer().browser()
    from_v1 = browser.get(detail("one", "entries", "e1"))
    from_v3 = browser.get(detail("three", "episodes", "e1"))
    assert series(from_v1, "views") == series(from_v3, "views")


# --------------------------------------------------------------------------
# Chart Data — Ordering Across Versions
# --------------------------------------------------------------------------

# Phrase: "v1 | Numeric comparison of UNIX-epoch string keys"
# Context: numerically 1000000000 > 999999999, lexicographically the reverse.
def test_v1_ordering_is_numeric_not_lexicographic(viewer, tmp_path):
    entry = v1_entry("e1", epoch=EPOCH_SMALL, views=5)
    entry["views"][EPOCH_BIG] = 9
    v1_vault(tmp_path, [entry])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert values(page, "views") == [5, 9]
    assert stamps(page, "views") == [EPOCH_SMALL_ISO, EPOCH_BIG_ISO]


# Phrase: "v1 chart ordering | By numeric epoch value, not lexicographic"
# Context: insertion order in the JSON file must not decide the chart order.
def test_v1_ordering_ignores_stored_key_order(viewer, tmp_path):
    entry = v1_entry("e1", epoch=EPOCH_BIG, views=9)
    entry["views"][EPOCH_SMALL] = 5
    entry["likes"][EPOCH_SMALL] = 1
    v1_vault(tmp_path, [entry])
    page = detail_page(viewer, tmp_path, "v", "entries", "e1")
    assert values(page, "views") == [5, 9]
    assert stamps(page, "likes") == [EPOCH_SMALL_ISO, EPOCH_BIG_ISO]


# Phrase: "v2 | Lexicographic comparison of ISO 8601 string keys"
def test_v2_ordering_is_lexicographic(viewer, tmp_path):
    entry = v2_entry("e1", stamp=T3, views=11)
    entry["views"][T2] = 9
    entry["views"][T1] = 5
    v2_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert stamps(page, "views") == [T1, T2, T3]


# Phrase: "v3 | Lexicographic comparison of ISO 8601 string keys"
def test_v3_ordering_is_lexicographic(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T3, views=11)
    entry["views"][T2] = 9
    entry["views"][T1] = 5
    v3_vault(tmp_path, episodes=[entry])
    page = detail_page(viewer, tmp_path, "v", "episodes", "e1")
    assert stamps(page, "views") == [T1, T2, T3]


# Phrase: "Chart point order | Chronological, oldest first"
# Context: determinism — the same vault renders the same payload every time.
def test_chart_payload_is_deterministic(viewer, tmp_path):
    entry = v3_entry("e1", stamp=T3, views=11)
    entry["views"][T1] = 5
    entry["views"][T2] = 9
    v3_vault(tmp_path, episodes=[entry])
    browser = viewer().browser()
    first = series(browser.get(detail("v", "episodes", "e1")), "views")
    second = series(browser.get(detail("v", "episodes", "e1")), "views")
    assert first == second == [(T1, 5), (T2, 9), (T3, 11)]


# --------------------------------------------------------------------------
# HTTP Error Handling (detail route)
# --------------------------------------------------------------------------

# Phrase: "Missing entry in specified category | HTTP `404`, or redirect to
#          category listing with error indication"
def test_missing_entry_is_404_or_redirect_with_error(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    browser = viewer().browser()
    page = browser.get(detail("v", "episodes", "ghost"))
    assert page.status in (404,) + REDIRECTS, (page.status, page.body[:200])
    if page.status in REDIRECTS:
        target = page.location
        assert "/catalog/v/episodes" in target, target
        _, landing = browser.follow(detail("v", "episodes", "ghost"))
        assert re.search(r"not\s*found|error|no\s+such", landing.body,
                         re.IGNORECASE), landing.body


# Phrase: "Non-existent vault on detail or static route | Redirect to landing
#          page with vault-not-found indication"
def test_missing_vault_on_detail_route_redirects_to_landing(viewer, tmp_path):
    browser = viewer().browser()
    page = browser.get(detail("ghost", "episodes", "e1"))
    assert page.status in REDIRECTS, (page.status, page.body[:200])
    landing = page.location.split("?")[0]
    assert landing.rstrip("/").endswith("") and landing.count("/") <= 3, \
        page.location
    _, final = browser.follow(detail("ghost", "episodes", "e1"))
    assert re.search(r"not\s*found", final.body, re.IGNORECASE), final.body


# Phrase: "Invalid category on detail route | Same handling allowed for invalid
#          category listing route"
@pytest.mark.parametrize("category", ["entries", "bogus"])
def test_invalid_category_on_detail_route(viewer, tmp_path, category):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    browser = viewer().browser()
    page = browser.get(detail("v", category, "e1"))
    listing = browser.get("/catalog/v/%s" % category)
    assert page.status in (400, 404) + REDIRECTS, (page.status, page.body[:200])
    assert page.status == listing.status, (page.status, listing.status)


# Phrase: "Invalid category on detail route"
# Context: v1 vaults reject the v3 category names.
def test_v1_rejects_v3_category_on_detail_route(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    page = viewer().browser().get(detail("v", "episodes", "e1"))
    assert page.status != 200
    assert page.status != 500


# Phrase: "Any HTTP error | Well-formed response; no raw stack trace or
#          internal detail exposure"
@pytest.mark.parametrize("path", ["/catalog/v/episodes/ghost",
                                  "/catalog/v/bogus/e1",
                                  "/catalog/ghost/episodes/e1"])
def test_detail_errors_have_no_traceback(viewer, tmp_path, path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    page = viewer().browser().get(path)
    assert page.status != 500
    assert "Traceback" not in page.body
    assert 'File "' not in page.body


# Phrase: "no raw stack trace or internal detail exposure"
# Context: a detail request against an unreadable catalog is not a crash.
def test_broken_catalog_detail_request_is_not_a_500(viewer, tmp_path):
    vault = tmp_path / "broken"
    vault.mkdir()
    (vault / "catalog.json").write_text("{not json", encoding="utf-8")
    page = viewer().browser().get(detail("broken", "episodes", "e1"))
    assert page.status != 500
    assert "Traceback" not in page.body
