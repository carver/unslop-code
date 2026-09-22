"""Spec section: `/catalog/<name>/<category>` Listing Rules."""

from conftest import (
    EPOCH_KEY,
    ISO_KEY,
    legacy_entry,
    v1_catalog,
    v2_catalog,
    v3_catalog,
    v3_entry,
    write_media,
    write_vault,
)

LATER = "2024-07-01T10:00:00"

#: Two epoch keys whose numeric order is the reverse of their text order.
EARLY_EPOCH = "999999999"
LATE_EPOCH = "1718444400"


def row_of(response, entry_id):
    """The single listing row describing one entry."""
    rows = [line for line in response.body.splitlines() if f'data-entry="{entry_id}"' in line]
    assert len(rows) == 1, f"expected one row for {entry_id} in:\n{response.body}"
    return rows[0]


def shape_of(response, entry_id):
    """One row's markup with the entry's own title and id blanked out.

    Two entries that are rendered in the same state share a shape, so a
    difference in shape is exactly a visible difference in state.
    """
    return row_of(response, entry_id).replace(f"title-{entry_id}", "").replace(entry_id, "")


# Spec: "| Category matching | Case-sensitive |".
def test_category_matching_is_case_sensitive(viewer, tmp_path):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")]))

    assert viewer.client.get("/catalog/demo/Episodes").status != 200
    assert viewer.client.get("/catalog/demo/episodes").status == 200


# Spec: "| Entry order | Same order as category array in `catalog.json` |".
def test_entries_are_listed_in_catalog_order(viewer, tmp_path):
    catalog = v3_catalog(
        "https://example.test/feed", episodes=[v3_entry("second"), v3_entry("first")]
    )
    write_vault(tmp_path, "demo", catalog)

    body = viewer.client.get("/catalog/demo/episodes").body

    assert body.index("title-second") < body.index("title-first")


# Spec: "| Current title | Latest value from `title` history, resolved using the
# vault version's key format |" with "| v2/v3 title resolution | Latest by
# lexicographic comparison of ISO 8601 string keys |".
def test_modern_listing_shows_the_latest_title(viewer, tmp_path):
    entry = v3_entry("e1", title={ISO_KEY: "old title", LATER: "current title"})
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[entry]))

    body = viewer.client.get("/catalog/demo/episodes").body

    assert "current title" in body
    assert "old title" not in body


# Spec: "| v1 title resolution | Latest by numeric comparison of UNIX-epoch
# string keys |" -- the numerically later key wins even though its text sorts
# first.
def test_v1_listing_resolves_titles_numerically(viewer, tmp_path):
    entry = legacy_entry("e1", EARLY_EPOCH, title={EARLY_EPOCH: "old title", LATE_EPOCH: "current title"})
    write_vault(tmp_path, "demo", v1_catalog(entry))

    body = viewer.client.get("/catalog/demo/entries").body

    assert "current title" in body
    assert "old title" not in body


# Spec: "| Downloaded state (v2/v3) | Entry counts as downloaded when a media
# filename in `<vault>/media/` contains entry `id` |" and "| Visual distinction
# | Downloaded and undownloaded states must be distinguishable |".
def test_downloaded_and_undownloaded_entries_are_distinguishable(viewer, tmp_path):
    catalog = v3_catalog("https://example.test/feed", episodes=[v3_entry("e1"), v3_entry("e2")])
    vault = write_vault(tmp_path, "demo", catalog)
    write_media(vault, "e1.mp4")

    response = viewer.client.get("/catalog/demo/episodes")

    assert shape_of(response, "e1") != shape_of(response, "e2")


# Spec: "| Downloaded state (v1) | Same rule as v2/v3 |".
def test_v1_downloaded_state_uses_the_same_rule(viewer, tmp_path):
    catalog = v1_catalog(legacy_entry("e1", EPOCH_KEY), legacy_entry("e2", EPOCH_KEY))
    vault = write_vault(tmp_path, "demo", catalog)
    write_media(vault, "e1.mp4")

    response = viewer.client.get("/catalog/demo/entries")

    assert shape_of(response, "e1") != shape_of(response, "e2")


# Spec: "| Downloaded state (v2/v3) | ... a media filename ... contains entry
# `id` |" -- a vault with no media directory lists every entry as undownloaded.
def test_entries_without_media_share_the_undownloaded_shape(viewer, tmp_path):
    catalog = v3_catalog("https://example.test/feed", episodes=[v3_entry("e1"), v3_entry("e2")])
    write_vault(tmp_path, "demo", catalog)

    response = viewer.client.get("/catalog/demo/episodes")

    assert shape_of(response, "e1") == shape_of(response, "e2")


# Spec: "| Removed indicator (v3 only) | Entries with latest `removed` value
# `true` are visually distinct from active entries |".
def test_removed_entries_are_visually_distinct(viewer, tmp_path):
    gone = v3_entry("gone", removed={ISO_KEY: False, LATER: True})
    catalog = v3_catalog("https://example.test/feed", episodes=[v3_entry("here"), gone])
    write_vault(tmp_path, "demo", catalog)

    response = viewer.client.get("/catalog/demo/episodes")

    assert shape_of(response, "here") != shape_of(response, "gone")


# Spec: "| Removed indicator (v1/v2) | Not applicable; no `removed` field
# exists |" -- every v2 entry is rendered in the same, active state.
def test_v2_entries_carry_no_removal_distinction(viewer, tmp_path):
    catalog = v2_catalog(
        "https://example.test/feed",
        episodes=[legacy_entry("e1", ISO_KEY), legacy_entry("e2", ISO_KEY)],
    )
    write_vault(tmp_path, "demo", catalog)

    response = viewer.client.get("/catalog/demo/episodes")

    assert shape_of(response, "e1") == shape_of(response, "e2")


# Spec: "| Entry navigation | Each listed entry includes a link to
# `/catalog/<name>/<category>/<id>` |".
def test_each_entry_links_to_its_own_page(viewer, tmp_path):
    catalog = v3_catalog("https://example.test/feed", streams=[v3_entry("s1")])
    write_vault(tmp_path, "demo", catalog)

    response = viewer.client.get("/catalog/demo/streams")

    assert 'href="/catalog/demo/streams/s1"' in row_of(response, "s1")
