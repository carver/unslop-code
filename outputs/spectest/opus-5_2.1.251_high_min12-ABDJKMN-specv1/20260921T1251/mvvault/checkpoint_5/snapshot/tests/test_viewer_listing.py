"""Spec section: `/catalog/<name>/<category>` Listing Rules."""

from __future__ import annotations


def media_file(vault, filename, body=b"bytes"):
    """Put a downloaded media file into `<vault>/media/`."""
    media = vault / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / filename).write_bytes(body)


# ---------------------------------------------------------------------------
# | Category matching | Case-sensitive |
# ---------------------------------------------------------------------------

# Spec: | Category matching | Case-sensitive |
# Context: `Episodes` is not the `episodes` category of a v3 vault.
def test_category_matching_rejects_wrong_case(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault/Episodes")
    assert response.status in (302, 303, 400, 404), response.status


# Spec: | Category matching | Case-sensitive |
# Context: an upper-case category never renders the listing itself.
def test_wrong_case_category_does_not_render_the_listing(
    serve, make_vault, catalogs
):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault/EPISODES")
    assert not (response.status == 200 and "Title e1" in response.body)


# Spec: | Category matching | Case-sensitive |
# Context: v1's only category is spelled exactly `entries`.
def test_v1_category_matching_rejects_wrong_case(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    response = serve().client.get("/catalog/vault/Entries")
    assert response.status in (302, 303, 400, 404), response.status


# ---------------------------------------------------------------------------
# | Entry order | Same order as category array in `catalog.json` |
# ---------------------------------------------------------------------------

# Spec: | Entry order | Same order as category array in `catalog.json` |
def test_entry_order_follows_the_catalog_array(serve, make_vault, catalogs,
                                               viewer_helpers):
    # Deliberately not sorted by id or by published date.
    make_vault(catalogs.catalog(episodes=[catalogs.entry("z9"),
                                          catalogs.entry("a1"),
                                          catalogs.entry("m5")]))
    body = serve().client.get("/catalog/vault/episodes").body
    assert viewer_helpers.order_of(body, ["z9", "a1", "m5"]) == ["z9", "a1", "m5"]


# Spec: | Listing order | Matches category-array order in `catalog.json` |
#   (Determinism)
# Context: repeated requests give the same order.
def test_listing_order_is_stable_across_requests(serve, make_vault, catalogs,
                                                 viewer_helpers):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("b"),
                                          catalogs.entry("a")]))
    client = serve().client
    first = viewer_helpers.order_of(
        client.get("/catalog/vault/episodes").body, ["a", "b"])
    second = viewer_helpers.order_of(
        client.get("/catalog/vault/episodes").body, ["a", "b"])
    assert first == second == ["b", "a"]


# Spec: | Entry order | Same order as category array in `catalog.json` |
# Context: v1's flat `entries` array order is preserved too.
def test_v1_entry_order_follows_the_entries_array(serve, make_vault, legacy,
                                                  viewer_helpers):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e2"),
                                          legacy.v1_entry("e1")]))
    body = serve().client.get("/catalog/vault/entries").body
    assert viewer_helpers.order_of(body, ["e1", "e2"]) == ["e2", "e1"]


# ---------------------------------------------------------------------------
# | Current title | Latest value from `title` history, resolved using the vault
#   version's key format |
# ---------------------------------------------------------------------------

# Spec: | Current title | Latest value from `title` history ... |
def test_listing_shows_the_current_title(serve, make_vault, catalogs):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "Stale", catalogs.STAMP_2: "Current"}
    make_vault(catalogs.catalog(episodes=[entry]))
    body = serve().client.get("/catalog/vault/episodes").body
    assert "Current" in body
    assert "Stale" not in body


# Spec: | v2/v3 title resolution | Latest by lexicographic comparison of
#   ISO 8601 string keys | (Determinism)
def test_v2_title_resolution_is_lexicographic(serve, make_vault, legacy):
    entry = legacy.v2_entry("e1")
    entry["title"] = {"2024-01-02T00:00:00": "Older",
                      "2024-11-30T00:00:00": "Newest",
                      "2024-02-03T00:00:00": "Middle"}
    make_vault(legacy.v2_catalog(episodes=[entry]))
    body = serve().client.get("/catalog/vault/episodes").body
    assert "Newest" in body
    assert "Older" not in body and "Middle" not in body


# Spec: | v1 title resolution | Latest by numeric comparison of UNIX-epoch
#   string keys | (Determinism)
# Context: `9` sorts after `100` numerically but before it lexicographically,
# so the two readings disagree on which title is current.
def test_v1_title_resolution_is_numeric(serve, make_vault, legacy):
    entry = legacy.v1_entry("e1")
    entry["title"] = {"9": "Lexicographically last", "100": "Numerically last"}
    make_vault(legacy.v1_catalog(entries=[entry]))
    body = serve().client.get("/catalog/vault/entries").body
    assert "Numerically last" in body
    assert "Lexicographically last" not in body


# Spec: | Current title | ... resolved using the vault version's key format |
# Context: a v1 vault is read as v1 even though the viewer never migrates it.
def test_v1_titles_render_without_migration(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1"),
                                          legacy.v1_entry("e2")]))
    body = serve().client.get("/catalog/vault/entries").body
    assert "Title e1" in body and "Title e2" in body


# ---------------------------------------------------------------------------
# | Downloaded state (v2/v3) | Entry counts as downloaded when a media filename
#   in `<vault>/media/` contains entry `id` |
# | Visual distinction | Downloaded and undownloaded states must be
#   distinguishable |
# ---------------------------------------------------------------------------

# Spec: | Visual distinction | Downloaded and undownloaded states must be
#   distinguishable |
def test_downloaded_and_undownloaded_entries_render_differently(
    serve, make_vault, catalogs, viewer_helpers, workdir
):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                                  catalogs.entry("e2")]))
    media_file(vault, "e1.mp4")
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/episodes").body)
    assert blocks["e1"].replace("e1", "") != blocks["e2"].replace("e2", ""), blocks


# Spec: | Downloaded state (v2/v3) | ... when a media filename in
#   `<vault>/media/` contains entry `id` |
# Context: "contains" - the file name need not equal `<id>.<ext>`.
def test_downloaded_state_matches_a_containing_filename(
    serve, make_vault, catalogs, viewer_helpers
):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                                  catalogs.entry("e2")]))
    media_file(vault, "prefix-e1-suffix.mp4")
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/episodes").body)
    assert blocks["e1"].replace("e1", "") != blocks["e2"].replace("e2", "")


# Spec: | Downloaded state ... | media filename in `<vault>/media/` ... |
# Context: files outside `<vault>/media/` do not count as downloads.
def test_preview_file_does_not_make_an_entry_downloaded(
    serve, make_vault, catalogs, viewer_helpers
):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                                  catalogs.entry("e2")]))
    previews = vault / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    (previews / "e1.jpg").write_bytes(b"x")
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/episodes").body)
    assert blocks["e1"].replace("e1", "") == blocks["e2"].replace("e2", "")


# Spec: | Downloaded state ... |
# Context: a vault with no `media/` directory at all lists every entry as
# undownloaded, and still renders.
def test_missing_media_directory_lists_everything_undownloaded(
    serve, make_vault, catalogs, viewer_helpers
):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                          catalogs.entry("e2")]))
    response = serve().client.get("/catalog/vault/episodes")
    assert response.status == 200
    blocks = viewer_helpers.entry_blocks(response.body)
    assert blocks["e1"].replace("e1", "") == blocks["e2"].replace("e2", "")


# Spec: | Downloaded state (v1) | Same rule as v2/v3 |
def test_v1_downloaded_state_uses_the_same_rule(
    serve, make_vault, legacy, viewer_helpers
):
    vault = make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1"),
                                                  legacy.v1_entry("e2")]))
    media_file(vault, "e1.mp4")
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/entries").body)
    assert blocks["e1"].replace("e1", "") != blocks["e2"].replace("e2", "")


# Spec: | Downloaded state (v2/v3) | ... |
# Context: the same distinction is drawn in a non-default category.
def test_downloaded_state_applies_to_clips(
    serve, make_vault, catalogs, viewer_helpers
):
    vault = make_vault(catalogs.catalog(clips=[catalogs.entry("c1"),
                                               catalogs.entry("c2")]))
    media_file(vault, "c2.webm")
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/clips").body)
    assert blocks["c1"].replace("c1", "") != blocks["c2"].replace("c2", "")


# ---------------------------------------------------------------------------
# | Removed indicator (v3 only) | Entries with latest `removed` value `true` are
#   visually distinct from active entries |
# ---------------------------------------------------------------------------

# Spec: | Removed indicator (v3 only) | Entries with latest `removed` value
#   `true` are visually distinct from active entries |
def test_removed_entries_are_visually_distinct(
    serve, make_vault, catalogs, viewer_helpers
):
    gone = catalogs.entry("e1")
    gone["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[gone, catalogs.entry("e2")]))
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/episodes").body)
    assert blocks["e1"].replace("e1", "") != blocks["e2"].replace("e2", "")


# Spec: | Removed indicator (v3 only) | ... latest `removed` value `true` ... |
# Context: an entry whose latest `removed` value is `false` is an active entry,
# even if it was removed earlier.
def test_reappeared_entry_is_not_marked_removed(
    serve, make_vault, catalogs, viewer_helpers
):
    back = catalogs.entry("e1")
    back["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True,
                       catalogs.STAMP_3: False}
    make_vault(catalogs.catalog(episodes=[back, catalogs.entry("e2")]))
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/episodes").body)
    assert blocks["e1"].replace("e1", "") == blocks["e2"].replace("e2", "")


# Spec: | Removed indicator (v1/v2) | Not applicable; no `removed` field exists |
def test_v2_listing_marks_nothing_removed(serve, make_vault, legacy,
                                          viewer_helpers):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1"),
                                           legacy.v2_entry("e2")]))
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/episodes").body)
    assert blocks["e1"].replace("e1", "") == blocks["e2"].replace("e2", "")


# Spec: | Removed indicator (v1/v2) | Not applicable ... |
def test_v1_listing_marks_nothing_removed(serve, make_vault, legacy,
                                          viewer_helpers):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1"),
                                          legacy.v1_entry("e2")]))
    blocks = viewer_helpers.entry_blocks(
        serve().client.get("/catalog/vault/entries").body)
    assert blocks["e1"].replace("e1", "") == blocks["e2"].replace("e2", "")


# ---------------------------------------------------------------------------
# | Entry navigation | Each listed entry includes a link to
#   `/catalog/<name>/<category>/<id>` |
# ---------------------------------------------------------------------------

# Spec: | Entry navigation | Each listed entry includes a link to
#   `/catalog/<name>/<category>/<id>` |
def test_each_entry_links_to_its_own_route(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                          catalogs.entry("e2")]))
    body = serve().client.get("/catalog/vault/episodes").body
    assert "/catalog/vault/episodes/e1" in body
    assert "/catalog/vault/episodes/e2" in body


# Spec: | Entry navigation | ... a link ... |
# Context: the target is an actual anchor href, and following it works.
def test_entry_link_is_followable(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(streams=[catalogs.entry("s1")]))
    process = serve()
    body = process.client.get("/catalog/vault/streams").body
    assert 'href="/catalog/vault/streams/s1"' in body, body
    assert process.client.get("/catalog/vault/streams/s1").status == 200


# Spec: | Entry navigation | ... to `/catalog/<name>/<category>/<id>` |
# Context: the category in the link is the category being listed, for v1 too.
def test_v1_entry_links_use_the_entries_category(serve, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    body = serve().client.get("/catalog/vault/entries").body
    assert "/catalog/vault/entries/e1" in body


# Spec: | Entry navigation | ... | (empty categories still render)
def test_empty_category_renders(serve, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    response = serve().client.get("/catalog/vault/clips")
    assert response.status == 200
    assert "e1" not in response.body
