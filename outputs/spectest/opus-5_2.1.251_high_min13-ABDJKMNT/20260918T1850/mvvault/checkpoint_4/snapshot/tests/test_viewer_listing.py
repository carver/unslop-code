"""Spec section: `/catalog/<name>/<category>` Listing Rules."""

import re

from conftest import (
    V1_EPOCH,
    V2_LATER,
    V2_STAMP,
    add_media,
    entry_rows,
    row_for,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)


def titles(html):
    """Entry titles in listing order."""
    return [re.search(r">([^<]*)</a>", row).group(1) for row in entry_rows(html)]


# Spec: Entry order | Same order as category array in `catalog.json`
def test_entries_follow_catalog_array_order(serve, tmp_path):
    entries = [v3_entry("e2"), v3_entry("e1"), v3_entry("e3")]
    write_vault(tmp_path, v3_catalog(episodes=entries))
    assert titles(serve().get("/catalog/vault/episodes").text) == [
        "Title e2",
        "Title e1",
        "Title e3",
    ]


# Spec: Listing order | Matches category-array order in `catalog.json`
# (repeated requests agree)
def test_listing_order_is_stable(serve, tmp_path):
    entries = [v3_entry("e2"), v3_entry("e1")]
    write_vault(tmp_path, v3_catalog(episodes=entries))
    viewer = serve()
    first = viewer.get("/catalog/vault/episodes").text
    assert first == viewer.get("/catalog/vault/episodes").text


# Spec: Current title | Latest value from `title` history
# Spec: v2/v3 title resolution | Latest by lexicographic comparison of ISO 8601 keys
def test_current_title_is_the_latest_iso_keyed_value(serve, tmp_path):
    entry = v3_entry("e1", title={V2_LATER: "Final title", V2_STAMP: "Working title"})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    body = serve().get("/catalog/vault/episodes").text
    assert "Final title" in body
    assert "Working title" not in body


# Spec: v1 title resolution | Latest by numeric comparison of UNIX-epoch string keys
def test_v1_current_title_is_the_latest_by_numeric_key(serve, tmp_path):
    entry = v1_entry("e1", title={"999": "Old title", V1_EPOCH: "Final title"})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    body = serve().get("/catalog/vault/entries").text
    assert "Final title" in body
    assert "Old title" not in body


# Spec: v2/v3 title resolution | ... resolved using the vault version's key format
def test_v2_current_title_is_the_latest_by_iso_key(serve, tmp_path):
    entry = v2_entry("e1", title={V2_STAMP: "Working title", V2_LATER: "Final title"})
    write_vault(tmp_path, v2_catalog(episodes=[entry]))
    assert "Final title" in serve().get("/catalog/vault/episodes").text


# Spec: Downloaded state (v2/v3) | Entry counts as downloaded when a media
# filename in `<vault>/media/` contains entry `id`
# Spec: Visual distinction | Downloaded and undownloaded states distinguishable
def test_downloaded_and_undownloaded_entries_are_distinguishable(serve, tmp_path):
    directory = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1"), v3_entry("e2")]))
    add_media(directory, "e1.mp4")

    body = serve().get("/catalog/vault/episodes").text
    assert row_for(body, "e1") != row_for(body, "e2")
    assert "downloaded" in row_for(body, "e1")
    assert "downloaded" not in row_for(body, "e2")


# Spec: Downloaded state | ... a media filename *contains* the entry id
def test_media_filename_only_has_to_contain_the_id(serve, tmp_path):
    directory = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    add_media(directory, "video-e1-1080p.mkv")
    assert "downloaded" in row_for(serve().get("/catalog/vault/episodes").text, "e1")


# Spec: Downloaded state (v1) | Same rule as v2/v3
def test_v1_downloaded_state_uses_the_same_rule(serve, tmp_path):
    directory = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1"), v1_entry("e2")]))
    add_media(directory, "e2.mp4")

    body = serve().get("/catalog/vault/entries").text
    assert "downloaded" in row_for(body, "e2")
    assert "downloaded" not in row_for(body, "e1")


# Spec: Downloaded state | a vault with no media directory at all
def test_entries_are_undownloaded_without_a_media_directory(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    assert "downloaded" not in row_for(serve().get("/catalog/vault/episodes").text, "e1")


# Spec: Removed indicator (v3 only) | Entries with latest `removed` value `true`
# are visually distinct from active entries
def test_removed_entries_are_visually_distinct(serve, tmp_path):
    entries = [
        v3_entry("e1"),
        v3_entry("e2", removed={V2_STAMP: False, V2_LATER: True}),
    ]
    write_vault(tmp_path, v3_catalog(episodes=entries))

    body = serve().get("/catalog/vault/episodes").text
    assert "removed" in row_for(body, "e2")
    assert "removed" not in row_for(body, "e1")


# Spec: Removed indicator | ... latest `removed` value (an entry that came back
# is active again)
def test_reappeared_entry_is_not_marked_removed(serve, tmp_path):
    entry = v3_entry("e1", removed={V2_STAMP: True, V2_LATER: False})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    assert "removed" not in row_for(serve().get("/catalog/vault/episodes").text, "e1")


# Spec: Removed indicator (v1/v2) | Not applicable; no `removed` field exists
def test_v2_listing_has_no_removed_indicator(serve, tmp_path):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")]))
    assert "removed" not in serve().get("/catalog/vault/episodes").text


# Spec: Removed indicator (v1/v2) | Not applicable
def test_v1_listing_has_no_removed_indicator(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    assert "removed" not in serve().get("/catalog/vault/entries").text


# Spec: Entry navigation | Each listed entry includes a link to
# `/catalog/<name>/<category>/<id>`
def test_each_entry_links_to_its_own_page(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(clips=[v3_entry("c1"), v3_entry("c2")]))
    body = serve().get("/catalog/vault/clips").text
    assert '"/catalog/vault/clips/c1"' in body
    assert '"/catalog/vault/clips/c2"' in body


# Spec: Entry navigation | ... the link is reachable
def test_entry_links_resolve(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(streams=[v3_entry("s1")]))
    assert serve().get("/catalog/vault/streams/s1").status_code == 200


# Spec: Entry order | Same order as category array (empty category still renders)
def test_empty_category_still_lists(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    response = serve().get("/catalog/vault/clips")
    assert response.status_code == 200
    assert entry_rows(response.text) == []
