"""Annotation Auto-Migration, its rules and the v1 category transition."""

import json

import pytest

from conftest import (
    EPOCH_KEY_ISO,
    ISO_KEY,
    SOURCE_URL,
    V1_SOURCE_URL,
    read_catalog,
    stored_annotations,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
)

V1_ENTRY = "/catalog/v/entries/a"
V3_ENTRY = "/catalog/v/episodes/a"


def location(response):
    """The `Location` of an unfollowed annotation redirect."""
    assert response.status_code in (302, 303), (response.status_code, response.text[:300])
    return response.headers["Location"]


def annotate(client, path, title="note", timecode="90"):
    """`POST` one annotation to `path`, whatever version the vault still is."""
    return client.send_json("POST", path, {"title": title, "timecode": timecode})


# Spec: v1 | Migrate entire catalog to v3 first, then apply annotation, then persist
def test_an_annotation_on_a_v1_vault_migrates_and_applies(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    location(annotate(client, V1_ENTRY))
    catalog = read_catalog(tmp_path / "v")
    assert catalog["version"] == 3
    assert [one["title"] for one in catalog["episodes"][0]["annotations"]] == ["note"]


# Spec: v2 | Migrate entire catalog to v3 first, then apply annotation, then persist
def test_an_annotation_on_a_v2_vault_migrates_and_applies(served, tmp_path):
    client = served(v2_catalog(SOURCE_URL, episodes=[v2_entry("a")]))
    location(annotate(client, V3_ENTRY))
    catalog = read_catalog(tmp_path / "v")
    assert catalog["version"] == 3
    assert [one["title"] for one in catalog["episodes"][0]["annotations"]] == ["note"]


# Spec: v3 | Apply annotation directly
def test_an_annotation_on_a_v3_vault_is_applied_directly(served, tmp_path):
    entry = v3_entry("a")
    client = served(v3_catalog(SOURCE_URL, episodes=[entry]))
    location(annotate(client, V3_ENTRY))
    catalog = read_catalog(tmp_path / "v")
    assert catalog["version"] == 3
    assert catalog["episodes"][0]["removed"] == entry["removed"]
    assert len(catalog["episodes"][0]["annotations"]) == 1


# Spec: Migration scope | Full catalog migration (same rules as `migrate` command)
def test_the_whole_catalog_is_migrated_not_just_the_annotated_entry(served, tmp_path):
    client = served(v1_catalog([v1_entry("a"), v1_entry("b")]))
    annotate(client, V1_ENTRY)
    other = next(row for row in read_catalog(tmp_path / "v")["episodes"] if row["id"] == "b")
    assert other["annotations"] == []
    assert list(other["removed"].values()) == [False]
    assert list(other["title"]) == [EPOCH_KEY_ISO]


# Spec: Migration scope | Full catalog migration (the native categories all appear)
def test_migration_writes_the_three_native_categories(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY)
    catalog = read_catalog(tmp_path / "v")
    assert [catalog["streams"], catalog["clips"]] == [[], []]
    assert "entries" not in catalog


# Spec: Backup before migration | `catalog.bak` contains the original
# pre-migration catalog
def test_the_backup_holds_the_pre_migration_catalog(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    before = (tmp_path / "v" / "catalog.json").read_text()
    annotate(client, V1_ENTRY)
    assert (tmp_path / "v" / "catalog.bak").read_text() == before


# Spec: Backup before annotation | If catalog was already v3, `catalog.bak`
# contains pre-annotation catalog
def test_the_backup_of_a_v3_vault_holds_the_pre_annotation_catalog(served, tmp_path):
    client = served(v3_catalog(SOURCE_URL, episodes=[v3_entry("a")]))
    before = (tmp_path / "v" / "catalog.json").read_text()
    annotate(client, V3_ENTRY)
    backup = json.loads((tmp_path / "v" / "catalog.bak").read_text())
    assert (tmp_path / "v" / "catalog.bak").read_text() == before
    assert backup["episodes"][0]["annotations"] == []


# Spec: Single write for migration + annotation | ... backup must reflect state
# before **both** changes
def test_the_backup_reflects_the_state_before_migration_and_annotation(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY)
    backup = json.loads((tmp_path / "v" / "catalog.bak").read_text())
    assert backup["version"] == 1
    assert "annotations" not in backup["entries"][0]


# Spec: v1 UNIX-epoch key conversion | Same rules as `migrate` command
def test_epoch_history_keys_are_converted_by_the_auto_migration(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY)
    entry = read_catalog(tmp_path / "v")["episodes"][0]
    assert list(entry["title"]) == [EPOCH_KEY_ISO]
    assert list(entry["views"]) == [EPOCH_KEY_ISO]


# Spec: v1 `source_id` conversion | Same rules as `migrate` command
def test_the_v1_source_id_is_converted_by_the_auto_migration(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY)
    catalog = read_catalog(tmp_path / "v")
    assert catalog["source"] == V1_SOURCE_URL
    assert "source_id" not in catalog


# Spec: Post auto-migration viewer routing | valid categories become `episodes`,
# `streams`, `clips`
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_the_native_categories_are_served_after_auto_migration(served, category):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY)
    assert client.get(f"/catalog/v/{category}").status_code == 200


# Spec: Post auto-migration viewer routing | v1 `entries` category is no longer valid
def test_the_v1_entries_category_stops_being_valid_after_auto_migration(served):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY)
    response = client.get("/catalog/v/entries", follow=False)
    assert response.status_code in (302, 303, 404)
    if response.status_code != 404:
        assert response.headers["Location"] == "/catalog/v/episodes"


# Spec: Retired GET behavior | Later `GET` requests to the retired v1 `entries`
# route may redirect to canonical v3 viewer routes or return `404`
def test_the_retired_entry_route_redirects_or_is_not_found(served):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY)
    response = client.get(V1_ENTRY, follow=False)
    assert response.status_code in (302, 303, 404)
    if response.status_code != 404:
        assert response.headers["Location"].startswith("/catalog/v/episodes")


# Spec: Request URL category | `entries` (v1 category name)
def test_the_annotation_request_targets_the_v1_category(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    assert annotate(client, V1_ENTRY).status_code in (302, 303)
    assert len(stored_annotations(tmp_path / "v")) == 1


# Spec: Request URL category | `entries` (the post-migration name is not the
# pre-migration route)
def test_the_post_migration_category_is_not_a_valid_v1_request_url(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    assert annotate(client, V3_ENTRY).status_code == 404
    assert read_catalog(tmp_path / "v")["version"] == 1


# Spec: Entry lookup | Find entry by `id` in the v1 `entries` array
def test_the_entry_is_found_by_id_inside_the_v1_entries_array(served, tmp_path):
    client = served(v1_catalog([v1_entry("a"), v1_entry("b"), v1_entry("c")]))
    annotate(client, "/catalog/v/entries/b", title="on b")
    assert [one["title"] for one in stored_annotations(tmp_path / "v", entry_id="b")] == ["on b"]
    assert stored_annotations(tmp_path / "v", entry_id="a") == []


# Spec: Post-migration location | Entry is in `episodes` after migration
def test_the_annotated_entry_lands_in_episodes(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY)
    assert [row["id"] for row in read_catalog(tmp_path / "v")["episodes"]] == ["a"]


# Spec: Redirect after success | Redirect uses post-migration category (`episodes`)
def test_the_redirect_after_a_v1_annotation_uses_episodes(served):
    client = served(v1_catalog([v1_entry("a")]))
    assert location(annotate(client, V1_ENTRY, timecode="1:30")) == f"{V3_ENTRY}?timecode=90"


# Spec: Subsequent requests | Must use `episodes` (v1 `entries` route is retired
# after migration)
def test_later_annotations_use_the_episodes_route(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY, title="first")
    assert annotate(client, V3_ENTRY, title="second").status_code in (302, 303)
    assert annotate(client, V1_ENTRY, title="third").status_code == 404
    assert [one["title"] for one in stored_annotations(tmp_path / "v")] == ["first", "second"]


# Spec: Pristine v1 and v2 catalogs do not define `annotations` ... `PATCH`/`DELETE`
# on legacy vaults are only meaningful after auto-migration
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_update_and_delete_on_a_pristine_v1_vault_find_no_annotation(served, tmp_path, method):
    client = served(v1_catalog([v1_entry("a")]))
    response = client.send_json(method, V1_ENTRY, {"id": "1", "title": "x"})
    assert response.status_code == 404
    assert read_catalog(tmp_path / "v")["version"] == 1


# Spec: ... such as after a prior successful `POST` in the same migrated vault
def test_update_works_after_a_prior_post_migrated_the_vault(served, tmp_path):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY, title="before")
    stored = stored_annotations(tmp_path / "v")[0]["id"]
    assert client.send_json("PATCH", V3_ENTRY, {"id": stored, "title": "after"}).status_code in (302, 303)
    assert [one["title"] for one in stored_annotations(tmp_path / "v")] == ["after"]


# Spec: Read-after-write behavior | Later `GET` to same entry detail page
# reflects create (after an auto-migration)
def test_the_migrated_detail_page_renders_the_new_annotation(served):
    client = served(v1_catalog([v1_entry("a")]))
    annotate(client, V1_ENTRY, title="migrated note")
    assert "migrated note" in client.get(V3_ENTRY).text


# Spec: Determinism | Auto-migration timestamp | Same timestamp used for all
# migration-added `removed` fields
def test_one_timestamp_keys_every_migration_added_removed_field(served, tmp_path):
    client = served(v1_catalog([v1_entry("a"), v1_entry("b"), v1_entry("c")]))
    annotate(client, V1_ENTRY)
    stamps = {key for row in read_catalog(tmp_path / "v")["episodes"] for key in row["removed"]}
    assert len(stamps) == 1


# Spec: Determinism | Post auto-migration category | v1 entries always migrate
# to `episodes`
def test_v1_entries_always_migrate_into_episodes(served, tmp_path):
    client = served(v1_catalog([v1_entry("a"), v1_entry("b")]))
    annotate(client, V1_ENTRY)
    catalog = read_catalog(tmp_path / "v")
    assert sorted(row["id"] for row in catalog["episodes"]) == ["a", "b"]
    assert catalog["streams"] == [] and catalog["clips"] == []


# Spec: Determinism | Redirect after v1 annotation | Uses `episodes`, not `entries`
def test_the_v1_redirect_never_names_the_entries_category(served):
    client = served(v1_catalog([v1_entry("a")]))
    assert "/entries/" not in location(annotate(client, V1_ENTRY))


# Spec: v2 | Migrate entire catalog to v3 first (the v2 entry gains `removed`)
def test_the_v2_auto_migration_adds_the_removed_field(served, tmp_path):
    client = served(v2_catalog(SOURCE_URL, episodes=[v2_entry("a")], clips=[v2_entry("c")]))
    annotate(client, V3_ENTRY)
    catalog = read_catalog(tmp_path / "v")
    assert list(catalog["episodes"][0]["removed"].values()) == [False]
    assert catalog["clips"][0]["annotations"] == []
    assert list(catalog["clips"][0]["title"]) == [ISO_KEY]
