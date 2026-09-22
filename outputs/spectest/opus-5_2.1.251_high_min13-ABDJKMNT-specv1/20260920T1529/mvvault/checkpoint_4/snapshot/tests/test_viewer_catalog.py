"""Spec sections: `/catalog` Routes, default-category redirect, listing rules."""

import pytest
from conftest import (
    V1_KEY,
    V1_OLDER_KEY,
    V2_KEY,
    V2_OLDER_KEY,
    catalog_bytes,
    place_media,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

REDIRECTS = (302, 303)
SOURCE = "https://example.test/a"


def entry_markup(body, entry_id):
    """The listing lines mentioning `entry_id`, with the id itself neutralised."""
    lines = [line for line in body.splitlines() if entry_id in line]
    assert lines, f"no markup for {entry_id}"
    return "\n".join(lines).replace(entry_id, "ID")


def v3_vault(tmp_path, name="demo", **categories):
    return write_vault(tmp_path, v3_catalog(SOURCE, **categories), name=name)


# `/catalog` Routes: "`GET` | `/catalog/<name>` | Redirect to default category
# page for vault"; Version-Aware Default Category Redirect: "v3 | `episodes`".
def test_v3_vault_redirects_to_episodes(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = viewer.get("/catalog/demo")

    assert response.status in REDIRECTS
    assert response.location == "/catalog/demo/episodes"


# Version-Aware Default Category Redirect: "v2 | `/catalog/<name>/episodes`".
def test_v2_vault_redirects_to_episodes(viewer, tmp_path):
    write_vault(tmp_path, v2_catalog(SOURCE, clips=[v2_entry("c1")]))

    assert viewer.get("/catalog/demo").location == "/catalog/demo/episodes"


# Version-Aware Default Category Redirect: "v1 | `/catalog/<name>/entries`".
def test_v1_vault_redirects_to_entries(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]))

    assert viewer.get("/catalog/demo").location == "/catalog/demo/entries"


# Intro: "The viewer works on vaults of any supported version without
# requiring prior migration."
def test_serving_a_legacy_vault_never_rewrites_it(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog([v1_entry("e1")]))
    before = catalog_bytes(vault)

    viewer.get("/catalog/demo", follow=True)

    assert catalog_bytes(vault) == before
    assert not (vault / "catalog.bak").exists()


# `/catalog` Routes: "`GET` | `/catalog/<name>/<category>` | HTML listing for
# category".
def test_category_listing_is_html_naming_its_entries(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])

    response = viewer.get("/catalog/demo/episodes")

    assert response.status == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "title-e1" in response.body
    assert "title-e2" in response.body


# Version-Aware Valid Categories: "v2 | `episodes`, `streams`, `clips`";
# "v3 | `episodes`, `streams`, `clips`".
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_serves_each_valid_category(viewer, tmp_path, category):
    v3_vault(tmp_path, **{category: [v3_entry("x1")]})

    response = viewer.get(f"/catalog/demo/{category}")

    assert response.status == 200
    assert "title-x1" in response.body


@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_serves_each_valid_category(viewer, tmp_path, category):
    write_vault(tmp_path, v2_catalog(SOURCE, **{category: [v2_entry("x1")]}))

    response = viewer.get(f"/catalog/demo/{category}")

    assert response.status == 200
    assert "title-x1" in response.body


# Version-Aware Valid Categories: "v1 | `entries`".
def test_v1_serves_its_entries_category(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]))

    response = viewer.get("/catalog/demo/entries")

    assert response.status == 200
    assert "title-e1" in response.body


# HTTP Error Handling: "Invalid category ... for v1 vault | Redirect to
# `/catalog/<name>/entries` or return HTTP `400`/`404`" — a v1 vault has no
# `episodes` category.
def test_v1_rejects_a_v3_category(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]))

    response = viewer.get("/catalog/demo/episodes")

    if response.status in REDIRECTS:
        assert response.location == "/catalog/demo/entries"
    else:
        assert response.status in (400, 404)


# HTTP Error Handling: "Invalid category ... for v2/v3 vault | Redirect to
# `/catalog/<name>/episodes` or return HTTP `400`/`404`" — `entries` is a v1
# category only.
def test_v3_rejects_the_v1_category(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = viewer.get("/catalog/demo/entries")

    if response.status in REDIRECTS:
        assert response.location == "/catalog/demo/episodes"
    else:
        assert response.status in (400, 404)


# HTTP Error Handling: "Invalid category on `GET /catalog/<name>/<category>`
# for v2/v3 vault" — an unknown word is no category at all.
def test_unknown_category_is_rejected(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = viewer.get("/catalog/demo/nonsense")

    assert response.status in REDIRECTS + (400, 404)
    assert "Traceback" not in response.body


# `/catalog/<name>/<category>` Listing Rules: "Category matching |
# Case-sensitive".
def test_category_matching_is_case_sensitive(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = viewer.get("/catalog/demo/Episodes")

    assert response.status in REDIRECTS + (400, 404)


# `/catalog/<name>/<category>` Listing Rules: "Entry order | Same order as
# category array in `catalog.json`" — catalog order, not sorted order.
def test_entries_are_listed_in_catalog_order(viewer, tmp_path):
    entries = [v3_entry("zz", published="2020-01-01T00:00:00"), v3_entry("aa")]
    v3_vault(tmp_path, episodes=entries)

    body = viewer.get("/catalog/demo/episodes").body

    assert body.index("title-zz") < body.index("title-aa")


# `/catalog/<name>/<category>` Listing Rules: "Current title | Latest value
# from `title` history"; Determinism: "v2/v3 title resolution | Latest by
# lexicographic comparison of ISO 8601 string keys".
def test_v3_title_is_the_latest_iso_keyed_value(viewer, tmp_path):
    entry = v3_entry("e1", title={V2_OLDER_KEY: "stale title", V2_KEY: "current title"})
    v3_vault(tmp_path, episodes=[entry])

    body = viewer.get("/catalog/demo/episodes").body

    assert "current title" in body
    assert "stale title" not in body


# Determinism: "v1 title resolution | Latest by numeric comparison of
# UNIX-epoch string keys" — `999999999` is text-greater but time-smaller.
def test_v1_title_is_the_latest_epoch_keyed_value(viewer, tmp_path):
    entry = v1_entry("e1", title={"999999999": "stale title", V1_KEY: "current title"})
    write_vault(tmp_path, v1_catalog([entry]))

    body = viewer.get("/catalog/demo/entries").body

    assert "current title" in body
    assert "stale title" not in body


# `/catalog/<name>/<category>` Listing Rules: "Downloaded state (v2/v3) |
# Entry counts as downloaded when a media filename in `<vault>/media/`
# contains entry `id`"; "Visual distinction | Downloaded and undownloaded
# states must be distinguishable".
def test_downloaded_entries_are_marked_differently(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])
    place_media(vault, "e1.mp4")

    body = viewer.get("/catalog/demo/episodes").body

    assert entry_markup(body, "e1") != entry_markup(body, "e2")


# `/catalog/<name>/<category>` Listing Rules: "Downloaded state (v1) | Same
# rule as v2/v3".
def test_v1_downloaded_state_uses_the_same_rule(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog([v1_entry("e1"), v1_entry("e2")]))
    place_media(vault, "prefix-e1-suffix.mp4")

    body = viewer.get("/catalog/demo/entries").body

    assert entry_markup(body, "e1") != entry_markup(body, "e2")


# `/catalog/<name>/<category>` Listing Rules: "Downloaded state ... when a
# media filename ... contains entry `id`" — a vault without a media directory
# lists every entry as undownloaded.
def test_vault_without_media_directory_lists_entries(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = viewer.get("/catalog/demo/episodes")

    assert response.status == 200
    assert "title-e1" in response.body


# `/catalog/<name>/<category>` Listing Rules: "Removed indicator (v3 only) |
# Entries with latest `removed` value `true` are visually distinct from active
# entries".
def test_removed_entries_are_marked_differently(viewer, tmp_path):
    removed = v3_entry("e1", removed={V2_OLDER_KEY: False, V2_KEY: True})
    v3_vault(tmp_path, episodes=[removed, v3_entry("e2")])

    body = viewer.get("/catalog/demo/episodes").body

    assert entry_markup(body, "e1") != entry_markup(body, "e2")


# `/catalog/<name>/<category>` Listing Rules: "Removed indicator (v1/v2) | Not
# applicable; no `removed` field exists" — a v2 listing marks nothing removed.
def test_v2_listing_has_no_removed_marking(viewer, tmp_path):
    write_vault(tmp_path, v2_catalog(SOURCE, episodes=[v2_entry("e1"), v2_entry("e2")]))

    body = viewer.get("/catalog/demo/episodes").body

    assert entry_markup(body, "e1") == entry_markup(body, "e2")
    assert "removed" not in entry_markup(body, "e1").lower()


# `/catalog/<name>/<category>` Listing Rules: "Entry navigation | Each listed
# entry includes a link to `/catalog/<name>/<category>/<id>`".
def test_each_entry_links_to_its_own_route(viewer, tmp_path):
    v3_vault(tmp_path, streams=[v3_entry("s1"), v3_entry("s2")])

    body = viewer.get("/catalog/demo/streams").body

    assert '"/catalog/demo/streams/s1"' in body
    assert '"/catalog/demo/streams/s2"' in body


# `/catalog` Routes: "`GET` | `/catalog/<name>/<category>/<id>` | HTML
# response for that viewer link target; may reuse the category listing page
# with the entry highlighted or otherwise surfaced".
def test_entry_route_serves_html_surfacing_the_entry(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])

    response = viewer.get("/catalog/demo/episodes/e1")

    assert response.status == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "title-e1" in response.body
    assert entry_markup(response.body, "e1") != entry_markup(response.body, "e2")


# `/catalog` Routes: "`GET` | `/catalog/<name>/<category>/<id>`" — an id that
# is not in the category still gets a well-formed page.
def test_entry_route_with_unknown_id_is_well_formed(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = viewer.get("/catalog/demo/episodes/missing")

    assert response.status in (200, 400, 404)
    assert "Traceback" not in response.body


# `/catalog/<name>/<category>` Listing Rules: "Entry order | Same order as
# category array" — v1 entries keep the order of the `entries` array.
def test_v1_entries_keep_their_array_order(viewer, tmp_path):
    entries = [v1_entry("b", key=V1_OLDER_KEY), v1_entry("a")]
    write_vault(tmp_path, v1_catalog(entries))

    body = viewer.get("/catalog/demo/entries").body

    assert body.index("title-b") < body.index("title-a")


# HTTP Error Handling: "Any HTTP error | Well-formed HTTP response; no raw
# exception or stack trace exposure" — including a bare `/catalog` request.
def test_bare_catalog_path_is_well_formed(viewer):
    response = viewer.get("/catalog")

    assert response.status in REDIRECTS + (400, 404)
    assert "Traceback" not in response.body
