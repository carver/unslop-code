"""Spec sections: `/catalog/<name>/<category>/<id>` Route and Lookup Rules."""

import pytest
from conftest import ISO_KEY, legacy_entry, v2_catalog, v3_catalog, v3_entry, write_vault
from detail_fixtures import VERSION_CASES, v1_vault, v2_vault, v3_vault

NOT_FOUND_STATUSES = (302, 303, 404)


# Phrase: "| `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for
# matching entry |".
@pytest.mark.parametrize("build, category, entry_id", VERSION_CASES)
def test_detail_route_returns_a_page_for_the_matching_entry(viewer, tmp_path, build, category, entry_id):
    build(tmp_path)

    response = viewer.client.get(f"/catalog/demo/{category}/{entry_id}")

    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/html")
    assert f"new-title-{entry_id}" in response.body


# Phrase: "| Category scope | Lookup occurs only inside named category |" -- an
# id that lives in `streams` is not found under `episodes`.
def test_lookup_is_scoped_to_the_named_category(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get("/catalog/demo/episodes/s1")

    assert response.status in NOT_FOUND_STATUSES


# Phrase: "| Cross-category duplicate IDs | Do not satisfy lookup |" -- the same
# id in two categories resolves separately in each, never across.
def test_duplicate_ids_resolve_within_their_own_category(viewer, tmp_path):
    catalog = v3_catalog(
        "https://example.test/feed",
        episodes=[v3_entry("dup", title={ISO_KEY: "episode-copy"})],
        clips=[v3_entry("dup", title={ISO_KEY: "clip-copy"})],
    )
    write_vault(tmp_path, "demo", catalog)

    assert "episode-copy" in viewer.client.get("/catalog/demo/episodes/dup").body
    assert "clip-copy" in viewer.client.get("/catalog/demo/clips/dup").body


# Phrase: "| Cross-category duplicate IDs | Do not satisfy lookup |" -- an id
# held only by `clips` is still unknown to the `streams` lookup.
def test_id_of_another_category_does_not_satisfy_lookup(viewer, tmp_path):
    catalog = v3_catalog("https://example.test/feed", clips=[v3_entry("only-clip")])
    write_vault(tmp_path, "demo", catalog)

    assert viewer.client.get("/catalog/demo/streams/only-clip").status in NOT_FOUND_STATUSES


# Phrase: "| Removed entries (v3) | Remain accessible on detail page |".
def test_removed_v3_entry_still_has_a_detail_page(viewer, tmp_path):
    v3_vault(tmp_path, removed={ISO_KEY: True})

    response = viewer.client.get("/catalog/demo/episodes/e1")

    assert response.status == 200
    assert "new-title-e1" in response.body


# Phrase: "| v1 lookup | Lookup in `entries` array when category is `entries` |".
def test_v1_looks_up_in_the_entries_array(viewer, tmp_path):
    v1_vault(tmp_path)

    assert viewer.client.get("/catalog/demo/entries/e1").status == 200


# Phrase: "| v2/v3 lookup | Lookup in matching category array |".
@pytest.mark.parametrize("category, entry_id", [("episodes", "e1"), ("streams", "s1"), ("clips", "c1")])
@pytest.mark.parametrize("build", [v2_vault, v3_vault])
def test_modern_lookup_uses_the_matching_category_array(viewer, tmp_path, build, category, entry_id):
    build(tmp_path)

    response = viewer.client.get(f"/catalog/demo/{category}/{entry_id}")

    assert response.status == 200
    assert f"new-title-{entry_id}" in response.body


# Phrase: "| v2/v3 lookup | Lookup in matching category array |" -- a v2 vault
# resolves the same way as a v3 one, without a `removed` history.
def test_v2_entry_without_removed_history_has_a_detail_page(viewer, tmp_path):
    catalog = v2_catalog("https://example.test/feed", episodes=[legacy_entry("e1", ISO_KEY)])
    write_vault(tmp_path, "demo", catalog)

    response = viewer.client.get("/catalog/demo/episodes/e1")

    assert response.status == 200
    assert "title-e1" in response.body
