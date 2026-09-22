"""Spec: the `/catalog/<name>/<category>` Listing Rules."""
import os

import pytest

from digest_helpers import K1, K2, K3, E1, E2, E3, v1, v1_entry, v2, v3, \
    v3_entry, legacy_entry
from viewer_helpers import hrefs, listed_ids, normalize, row_for


def add_media(directory, *filenames):
    """Drop finished media files into `<vault>/media/`."""
    media = os.path.join(str(directory), "media")
    os.makedirs(media, exist_ok=True)
    for filename in filenames:
        with open(os.path.join(media, filename), "wb") as fh:
            fh.write(b"BYTES")
    return media


# Spec: "| Category matching | Case-sensitive |" -- an upper-case category is
# not the valid lower-case one.
def test_category_matching_is_case_sensitive(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="One")]))
    response = serve().get("/catalog/vault/Episodes")
    assert response.status in (302, 303, 400, 404), response
    if response.is_redirect:
        assert response.location == "/catalog/vault/episodes"


# Spec: "| Category matching | Case-sensitive |" -- for v1 too.
def test_v1_category_matching_is_case_sensitive(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    response = serve().get("/catalog/vault/ENTRIES")
    assert response.status in (302, 303, 400, 404), response
    if response.is_redirect:
        assert response.location == "/catalog/vault/entries"


# Spec: "| Entry order | Same order as category array in `catalog.json` |" --
# the stored order is preserved even when it is not sorted by id.
def test_entry_order_follows_catalog_array(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="c3"), v3_entry(id="a1"),
                            v3_entry(id="b2")]))
    body = serve().get("/catalog/vault/episodes").body
    assert listed_ids(body, "vault", "episodes") == ["c3", "a1", "b2"]


# Spec: "| Entry order | Same order as category array in `catalog.json` |" --
# and not sorted by `published` either.
def test_entry_order_is_not_resorted_by_published(serve, make_vault):
    make_vault(v3(episodes=[
        v3_entry(id="old", published="2020-01-01T00:00:00"),
        v3_entry(id="new", published="2030-01-01T00:00:00"),
    ]))
    body = serve().get("/catalog/vault/episodes").body
    assert listed_ids(body, "vault", "episodes") == ["old", "new"]


# Spec: "| Entry order | ... |" -- v1's flat `entries` array likewise.
def test_v1_entry_order_follows_catalog_array(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="z9"), v1_entry(id="a1")]))
    body = serve().get("/catalog/vault/entries").body
    assert listed_ids(body, "vault", "entries") == ["z9", "a1"]


# Spec: "| Current title | Latest value from `title` history, resolved using
# the vault version's key format |" -- v3 ISO keys, latest wins.
def test_v3_current_title_is_the_latest_history_value(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     title={K1: "Oldest", K2: "Middle",
                                            K3: "Newest"})]))
    body = serve().get("/catalog/vault/episodes").body
    assert "Newest" in body
    assert "Oldest" not in body


# Spec: "| v2/v3 title resolution | Latest by lexicographic comparison of ISO
# 8601 string keys |" -- insertion order in the JSON object is irrelevant.
def test_v3_title_ignores_json_insertion_order(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     title={K3: "Newest", K1: "Oldest"})]))
    body = serve().get("/catalog/vault/episodes").body
    assert "Newest" in body
    assert "Oldest" not in body


# Spec: "| v2/v3 title resolution | Latest by lexicographic comparison of ISO
# 8601 string keys |" -- v2 as well.
def test_v2_current_title_is_the_latest_history_value(serve, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1",
                                         title={K1: "Oldest", K2: "Newest"})]))
    body = serve().get("/catalog/vault/episodes").body
    assert "Newest" in body
    assert "Oldest" not in body


# Spec: "| v1 title resolution | Latest by numeric comparison of UNIX-epoch
# string keys |" -- "1700000000" is numerically later than "999999999" even
# though it sorts earlier as a string.
def test_v1_title_uses_numeric_key_comparison(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title={"999999999": "Lexically Last",
                                                    "1700000000": "Numerically Last"})]))
    body = serve().get("/catalog/vault/entries").body
    assert "Numerically Last" in body
    assert "Lexically Last" not in body


# Spec: "| v1 title resolution | Latest by numeric comparison ... |" -- with
# same-width keys the two orderings agree; the latest still wins.
def test_v1_title_latest_epoch_key_wins(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title={E1: "Old", E2: "Mid",
                                                    E3: "New"})]))
    body = serve().get("/catalog/vault/entries").body
    assert "New" in body
    assert "Old" not in body


# Spec: "| Downloaded state (v2/v3) | Entry counts as downloaded when a media
# filename in `<vault>/media/` contains entry `id` |" + "| Visual distinction |
# Downloaded and undownloaded states must be distinguishable |"
def test_downloaded_and_undownloaded_rows_differ(serve, make_vault):
    directory = make_vault(v3(episodes=[v3_entry(id="e1", title="T"),
                                        v3_entry(id="e2", title="T")]))
    add_media(directory, "e1.mp4")
    body = serve().get("/catalog/vault/episodes").body
    downloaded = row_for(body, "e1")
    undownloaded = row_for(body, "e2")
    assert downloaded and undownloaded, body
    assert normalize(downloaded, "e1", "T") != normalize(undownloaded, "e2", "T")


# Spec: "| Downloaded state (v2/v3) | Entry counts as downloaded when a media
# filename ... contains entry `id` |" -- with no media directory at all, no
# entry is downloaded.
def test_no_media_directory_means_nothing_downloaded(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="T"),
                            v3_entry(id="e2", title="T")]))
    body = serve().get("/catalog/vault/episodes").body
    assert normalize(row_for(body, "e1"), "e1", "T") == \
        normalize(row_for(body, "e2"), "e2", "T")


# Spec: "| Downloaded state (v2/v3) | ... a media filename ... *contains* entry
# `id` |" -- the match is containment, not an exact filename.
def test_downloaded_match_is_containment(serve, make_vault):
    directory = make_vault(v3(episodes=[v3_entry(id="e1", title="T"),
                                        v3_entry(id="e2", title="T")]))
    add_media(directory, "prefix-e1-suffix.mp4")
    body = serve().get("/catalog/vault/episodes").body
    assert normalize(row_for(body, "e1"), "e1", "T") != \
        normalize(row_for(body, "e2"), "e2", "T")


# Spec: "| Downloaded state (v2/v3) | ... in `<vault>/media/` ... |" -- a file
# that only lives under `previews/` does not make an entry downloaded.
def test_preview_file_does_not_count_as_downloaded(serve, make_vault, tmp_path):
    make_vault(v3(episodes=[v3_entry(id="e1", title="T"),
                            v3_entry(id="e2", title="T")]))
    previews = tmp_path / "vault" / "previews"
    previews.mkdir(parents=True)
    (previews / "e1.jpg").write_bytes(b"P")
    body = serve().get("/catalog/vault/episodes").body
    assert normalize(row_for(body, "e1"), "e1", "T") == \
        normalize(row_for(body, "e2"), "e2", "T")


# Spec: "| Downloaded state (v1) | Same rule as v2/v3 |"
def test_v1_downloaded_state_uses_the_same_rule(serve, make_vault):
    directory = make_vault(v1(entries=[v1_entry(id="e1", title={E1: "T"}),
                                       v1_entry(id="e2", title={E1: "T"})]))
    add_media(directory, "e1.mp4")
    body = serve().get("/catalog/vault/entries").body
    assert normalize(row_for(body, "e1"), "e1", "T") != \
        normalize(row_for(body, "e2"), "e2", "T")


# Spec: "| Downloaded state | ... |" -- the same rule holds in every v2/v3
# category, not just `episodes`.
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_downloaded_state_in_every_category(serve, make_vault, category):
    directory = make_vault(v3(**{category: [v3_entry(id="x1", title="T"),
                                            v3_entry(id="x2", title="T")]}))
    add_media(directory, "x1.mp4")
    body = serve().get("/catalog/vault/%s" % category).body
    assert normalize(row_for(body, "x1"), "x1", "T") != \
        normalize(row_for(body, "x2"), "x2", "T")


# Spec: "| Removed indicator (v3 only) | Entries with latest `removed` value
# `true` are visually distinct from active entries |"
def test_removed_entries_are_visually_distinct(serve, make_vault):
    make_vault(v3(episodes=[
        v3_entry(id="e1", title="T", removed={K1: False}),
        v3_entry(id="e2", title="T", removed={K1: False, K2: True}),
    ]))
    body = serve().get("/catalog/vault/episodes").body
    assert normalize(row_for(body, "e1"), "e1", "T") != \
        normalize(row_for(body, "e2"), "e2", "T")


# Spec: "| Removed indicator (v3 only) | Entries with *latest* `removed` value
# `true` ... |" -- an entry restored to `false` reads as active again.
def test_restored_entry_is_not_marked_removed(serve, make_vault):
    make_vault(v3(episodes=[
        v3_entry(id="e1", title="T", removed={K1: False}),
        v3_entry(id="e2", title="T", removed={K1: True, K2: False}),
    ]))
    body = serve().get("/catalog/vault/episodes").body
    assert normalize(row_for(body, "e1"), "e1", "T") == \
        normalize(row_for(body, "e2"), "e2", "T")


# Spec: "| Removed indicator (v1/v2) | Not applicable; no `removed` field
# exists |" -- every v2 entry renders as an active entry.
def test_v2_entries_are_never_marked_removed(serve, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1", title={K1: "T"}),
                            legacy_entry(id="e2", title={K1: "T"})]))
    body = serve().get("/catalog/vault/episodes").body
    assert normalize(row_for(body, "e1"), "e1", "T") == \
        normalize(row_for(body, "e2"), "e2", "T")


# Spec: "| Removed indicator (v1/v2) | Not applicable ... |" -- a v1 listing
# renders without a removed marker and without erroring.
def test_v1_listing_has_no_removed_marker(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title={E1: "T"})]))
    body = serve().get("/catalog/vault/entries").body
    assert "T" in body
    assert "Traceback" not in body


# Spec: "| Entry navigation | Each listed entry includes a link to
# `/catalog/<name>/<category>/<id>` |"
def test_each_entry_links_to_its_entry_page(serve, make_vault):
    make_vault(v3(streams=[v3_entry(id="s1"), v3_entry(id="s2")]))
    body = serve().get("/catalog/vault/streams").body
    assert "/catalog/vault/streams/s1" in hrefs(body)
    assert "/catalog/vault/streams/s2" in hrefs(body)


# Spec: "| Entry navigation | ... |" -- on the v1 `entries` page too.
def test_v1_entries_link_to_entry_pages(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    body = serve().get("/catalog/vault/entries").body
    assert "/catalog/vault/entries/e1" in hrefs(body)


# Spec: "| Back navigation | Link to current vault/category listing |" -- the
# detail page leads back to a listing that still holds catalog-array order.
def test_detail_page_leads_back_to_the_ordered_listing(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="c3"), v3_entry(id="a1")]))
    server = serve()
    detail = server.get("/catalog/vault/episodes/a1")
    assert "/catalog/vault/episodes" in hrefs(detail.body)
    listing = server.get("/catalog/vault/episodes").body
    assert listed_ids(listing, "vault", "episodes") == ["c3", "a1"]


# Spec: "| `GET` | `/catalog/<name>/<category>` | HTML listing for category |"
# -- an empty category is still a well-formed page.
def test_empty_category_listing(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    response = serve().get("/catalog/vault/clips")
    assert response.status == 200, response
    assert listed_ids(response.body, "vault", "clips") == []
