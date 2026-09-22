"""`/catalog` Routes, Version-Aware Categories and Listing Rules."""

import re

import pytest

from conftest import SOURCE_URL, v1_catalog, v1_entry, v2_catalog, v2_entry, v3_catalog, v3_entry

#: Two epoch keys whose numeric order is the reverse of their text order.
OLD_EPOCH, NEW_EPOCH = "999999999", "1718444400"

#: Two ISO keys, oldest first.
OLD_ISO, NEW_ISO = "2024-01-01T00:00:00", "2024-06-15T09:40:00"


def location(response):
    assert response.status_code in (302, 303), response.status_code
    return response.headers["Location"]


def listed_ids(html, name="v", category="episodes"):
    """Entry ids linked from a listing page, in document order."""
    return re.findall(rf'href="/catalog/{name}/{category}/([^"]+)"', html)


def row_for(html, entry_id, name="v", category="episodes"):
    """The single listing line that carries `entry_id`'s viewer link."""
    href = f'href="/catalog/{name}/{category}/{entry_id}"'
    matches = [line.strip() for line in html.splitlines() if href in line]
    assert len(matches) == 1, html
    return matches[0]


def without_identity(row, entry_id):
    """A listing line with its entry-specific text blanked out.

    Two rows that still differ afterwards differ in how they are presented,
    not merely in which entry they name.
    """
    return row.replace(f"title-{entry_id}", "TITLE").replace(entry_id, "ID")


# Spec: `GET` | `/catalog/<name>` | Redirect to default category page for vault
# Spec: v3 | `/catalog/<name>/episodes`
def test_catalog_redirects_to_the_default_category(served):
    response = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])).get("/catalog/v", follow=False)
    assert location(response) == "/catalog/v/episodes"


# Spec: Version-Aware Default Category Redirect | v1 | `/catalog/<name>/entries`
def test_v1_redirects_to_entries(served):
    response = served(v1_catalog([v1_entry("a")])).get("/catalog/v", follow=False)
    assert location(response) == "/catalog/v/entries"


# Spec: Version-Aware Default Category Redirect | v2 | `/catalog/<name>/episodes`
def test_v2_redirects_to_episodes(served):
    response = served(v2_catalog(SOURCE_URL, episodes=[v2_entry("a")])).get("/catalog/v", follow=False)
    assert location(response) == "/catalog/v/episodes"


# Spec: Redirect status | HTTP `302` or `303`
def test_catalog_redirect_uses_a_redirect_status(served):
    response = served(v3_catalog(SOURCE_URL)).get("/catalog/v", follow=False)
    assert response.status_code in (302, 303)


# Spec: The viewer works on vaults of any supported version without requiring
# prior migration.
@pytest.mark.parametrize(
    "catalog, category",
    [
        (v1_catalog([v1_entry("a")]), "entries"),
        (v2_catalog(SOURCE_URL, episodes=[v2_entry("a")]), "episodes"),
        (v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]), "episodes"),
    ],
)
def test_every_supported_version_can_be_listed(served, catalog, category):
    response = served(catalog).get(f"/catalog/v/{category}")
    assert response.status_code == 200
    assert "title-a" in response.text


# Spec: The viewer works on vaults ... without requiring prior migration (the
# catalog on disk keeps its version)
def test_viewing_a_legacy_vault_does_not_migrate_it(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    client.get("/catalog/v/entries")
    assert '"version": 1' in (tmp_path / "v" / "catalog.json").read_text()
    assert not (tmp_path / "v" / "catalog.bak").exists()


# Spec: `GET` | `/catalog/<name>/<category>` | HTML listing for category
def test_category_listing_is_html(served):
    response = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])).get("/catalog/v/episodes")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]


# Spec: `GET` | `/catalog/<name>/<category>/<id>` | HTML response for that
# viewer link target
def test_entry_route_answers_with_html(served):
    response = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])).get("/catalog/v/episodes/a")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "title-a" in response.text


# Spec: `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for
# matching entry (AMBIGUITIES T49: the route is a page of its own, not the
# listing with one row marked, so the other entries are not on it)
def test_entry_route_is_a_page_about_one_entry(served):
    client = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a"), v3_entry("b")]))
    entry_page = client.get("/catalog/v/episodes/a").text
    assert "title-a" in entry_page
    assert "title-b" not in entry_page


# Spec: Version-Aware Valid Categories | v2 | `episodes`, `streams`, `clips`
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_categories_are_all_valid(served, category):
    catalog = v2_catalog(SOURCE_URL, **{category: [v2_entry("a")]})
    response = served(catalog).get(f"/catalog/v/{category}", follow=False)
    assert response.status_code == 200
    assert "title-a" in response.text


# Spec: Version-Aware Valid Categories | v3 | `episodes`, `streams`, `clips`
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_categories_are_all_valid(served, category):
    catalog = v3_catalog(SOURCE_URL, **{category: [v3_entry("a")]})
    response = served(catalog).get(f"/catalog/v/{category}", follow=False)
    assert response.status_code == 200


# Spec: Version-Aware Valid Categories | v1 | `entries`
def test_v1_entries_category_is_valid(served):
    response = served(v1_catalog([v1_entry("a")])).get("/catalog/v/entries", follow=False)
    assert response.status_code == 200


# Spec: Invalid category ... for v1 vault | Redirect to `/catalog/<name>/entries`
# or return HTTP `400`/`404`
@pytest.mark.parametrize("category", ["episodes", "streams", "clips", "bogus"])
def test_invalid_category_on_a_v1_vault(served, category):
    response = served(v1_catalog([v1_entry("a")])).get(f"/catalog/v/{category}", follow=False)
    assert response.status_code in (302, 303, 400, 404)
    if response.status_code in (302, 303):
        assert response.headers["Location"] == "/catalog/v/entries"


# Spec: Invalid category ... for v2/v3 vault | Redirect to
# `/catalog/<name>/episodes` or return HTTP `400`/`404`
@pytest.mark.parametrize("catalog", [v2_catalog(SOURCE_URL), v3_catalog(SOURCE_URL)])
def test_invalid_category_on_a_v2_or_v3_vault(served, catalog):
    response = served(catalog).get("/catalog/v/entries", follow=False)
    assert response.status_code in (302, 303, 400, 404)
    if response.status_code in (302, 303):
        assert response.headers["Location"] == "/catalog/v/episodes"


# Spec: Category matching | Case-sensitive
def test_category_matching_is_case_sensitive(served):
    response = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])).get("/catalog/v/Episodes", follow=False)
    assert response.status_code in (302, 303, 400, 404)


# Spec: Entry order | Same order as category array in `catalog.json`
def test_entries_are_listed_in_catalog_order(served):
    episodes = [
        v3_entry("a", published="2024-01-01T00:00:00"),
        v3_entry("b", published="2024-09-01T00:00:00"),
        v3_entry("c", published="2024-05-01T00:00:00"),
    ]
    client = served(v3_catalog(SOURCE_URL, episodes=episodes))
    assert listed_ids(client.get("/catalog/v/episodes").text) == ["a", "b", "c"]


# Spec: Entry order | Same order as category array in `catalog.json` (v1)
def test_v1_entries_are_listed_in_catalog_order(served):
    client = served(v1_catalog([v1_entry("c"), v1_entry("a"), v1_entry("b")]))
    assert listed_ids(client.get("/catalog/v/entries").text, category="entries") == ["c", "a", "b"]


# Spec: Current title | Latest value from `title` history
def test_listing_shows_the_latest_title(served):
    entry = v3_entry("a", title={OLD_ISO: "old title", NEW_ISO: "new title"})
    body = served(v3_catalog(SOURCE_URL, episodes=[entry])).get("/catalog/v/episodes").text
    assert "new title" in body
    assert "old title" not in body


# Spec: v2/v3 title resolution | Latest by lexicographic comparison of ISO 8601
# string keys
def test_v2_title_resolution_is_lexicographic(served):
    entry = v2_entry("a", title={OLD_ISO: "old title", NEW_ISO: "new title"})
    body = served(v2_catalog(SOURCE_URL, episodes=[entry])).get("/catalog/v/episodes").text
    assert "new title" in body
    assert "old title" not in body


# Spec: v1 title resolution | Latest by numeric comparison of UNIX-epoch string
# keys (text order would pick the older key here)
def test_v1_title_resolution_is_numeric(served):
    entry = v1_entry("a", title={OLD_EPOCH: "old title", NEW_EPOCH: "new title"})
    body = served(v1_catalog([entry])).get("/catalog/v/entries").text
    assert "new title" in body
    assert "old title" not in body


# Spec: Downloaded state (v2/v3) | Entry counts as downloaded when a media
# filename in `<vault>/media/` contains entry `id`
# Spec: Visual distinction | Downloaded and undownloaded states must be
# distinguishable
def test_downloaded_and_undownloaded_entries_look_different(served):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("a"), v3_entry("b")])
    body = served(catalog, media=["a.mp4"]).get("/catalog/v/episodes").text
    assert without_identity(row_for(body, "a"), "a") != without_identity(row_for(body, "b"), "b")


# Spec: Downloaded state (v2/v3) | ... when a media filename contains entry `id`
def test_a_media_filename_containing_the_id_counts_as_downloaded(served):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("a"), v3_entry("b")])
    with_extra = served(catalog, media=["prefix-a-suffix.mp4"]).get("/catalog/v/episodes").text
    assert without_identity(row_for(with_extra, "a"), "a") != without_identity(row_for(with_extra, "b"), "b")


# Spec: Downloaded state (v1) | Same rule as v2/v3
def test_v1_downloaded_state_uses_the_same_rule(served):
    catalog = v1_catalog([v1_entry("a"), v1_entry("b")])
    body = served(catalog, media=["a.mp4"]).get("/catalog/v/entries").text
    rows = [row_for(body, entry_id, category="entries") for entry_id in ("a", "b")]
    assert without_identity(rows[0], "a") != without_identity(rows[1], "b")


# Spec: Downloaded state | ... (a vault without a media directory lists fine)
def test_listing_without_a_media_directory_still_renders(served):
    body = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")])).get("/catalog/v/episodes").text
    assert "title-a" in body


# Spec: Removed indicator (v3 only) | Entries with latest `removed` value `true`
# are visually distinct from active entries
def test_removed_entries_are_visually_distinct(served):
    episodes = [
        v3_entry("a", removed={OLD_ISO: False, NEW_ISO: True}),
        v3_entry("b", removed={OLD_ISO: True, NEW_ISO: False}),
    ]
    body = served(v3_catalog(SOURCE_URL, episodes=episodes)).get("/catalog/v/episodes").text
    assert without_identity(row_for(body, "a"), "a") != without_identity(row_for(body, "b"), "b")


# Spec: Removed indicator (v1/v2) | Not applicable; no `removed` field exists
@pytest.mark.parametrize(
    "catalog, category",
    [(v1_catalog([v1_entry("a")]), "entries"), (v2_catalog(SOURCE_URL, episodes=[v2_entry("a")]), "episodes")],
)
def test_legacy_listings_render_without_a_removed_field(served, catalog, category):
    response = served(catalog).get(f"/catalog/v/{category}")
    assert response.status_code == 200
    assert "title-a" in response.text


# Spec: Entry navigation | Each listed entry includes a link to
# `/catalog/<name>/<category>/<id>`
def test_each_entry_links_to_its_own_route(served):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("a")], clips=[v3_entry("c")])
    client = served(catalog)
    assert listed_ids(client.get("/catalog/v/episodes").text) == ["a"]
    assert listed_ids(client.get("/catalog/v/clips").text, category="clips") == ["c"]


# Spec: Listing order | Matches category-array order in `catalog.json`
# (deterministic across repeated requests)
def test_listing_order_is_stable_across_requests(served):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("c"), v3_entry("a"), v3_entry("b")])
    client = served(catalog)
    first = listed_ids(client.get("/catalog/v/episodes").text)
    assert first == ["c", "a", "b"]
    assert listed_ids(client.get("/catalog/v/episodes").text) == first
