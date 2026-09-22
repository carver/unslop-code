"""Spec sections: Annotation Auto-Migration, Auto-Migration Rules, and
Auto-Migration -- Category Transition."""

import pytest

from conftest import (
    V1_EPOCH,
    V1_EPOCH_ISO,
    V1_SOURCE_TEMPLATE,
    V2_STAMP,
    annotation_titles,
    create,
    entry_route,
    is_redirect,
    location,
    read_backup,
    read_catalog,
    stored_annotations,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

V1_ROUTE = entry_route("vault", "entries", "e1")
V3_ROUTE = entry_route("vault", "episodes", "e1")


@pytest.fixture
def legacy_v1(serve, tmp_path):
    """A viewer over an untouched v1 vault holding one entry."""
    vault_dir = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    return serve(), vault_dir


# Spec: v1 | Migrate entire catalog to v3 first, then apply annotation, then persist
def test_a_v1_vault_is_migrated_by_a_create(legacy_v1):
    viewer, vault_dir = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="1:30")
    catalog = read_catalog(vault_dir)
    assert catalog["version"] == 3
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Chorus"]


# Spec: v2 | Migrate entire catalog to v3 first, then apply annotation, then persist
def test_a_v2_vault_is_migrated_by_a_create(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")]))
    create(serve(), V3_ROUTE, title="Chorus", timecode="1:30")
    assert read_catalog(vault_dir)["version"] == 3
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Chorus"]


# Spec: v3 | Apply annotation directly
def test_a_v3_vault_is_not_rewritten_by_migration(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    before = read_catalog(vault_dir)["episodes"][0]
    create(serve(), V3_ROUTE, title="Chorus", timecode="1:30")
    after = read_catalog(vault_dir)["episodes"][0]
    assert {key: value for key, value in after.items() if key != "annotations"} == {
        key: value for key, value in before.items() if key != "annotations"
    }


# Spec: Migration scope | Full catalog migration (same rules as `migrate` command)
def test_every_entry_gains_the_v3_fields_not_just_the_annotated_one(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1"), v1_entry("e2")]))
    create(serve(), V1_ROUTE, title="Chorus", timecode="1:30")
    for entry in read_catalog(vault_dir)["episodes"]:
        assert "removed" in entry and "annotations" in entry


# Spec: Backup before migration | `catalog.bak` contains the original pre-migration catalog
def test_the_backup_is_the_original_v1_catalog(legacy_v1):
    viewer, vault_dir = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="1:30")
    assert read_backup(vault_dir) == v1_catalog(entries=[v1_entry("e1")])


# Spec: Single write for migration + annotation | ... backup must reflect state
# before **both** changes
def test_the_backup_predates_both_the_migration_and_the_annotation(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")]))
    create(serve(), V3_ROUTE, title="Chorus", timecode="1:30")
    backup = read_backup(vault_dir)
    assert backup["version"] == 2
    assert "annotations" not in backup["episodes"][0]


# Spec: v1 UNIX-epoch key conversion | Same rules as `migrate` command
def test_v1_epoch_history_keys_are_converted(legacy_v1):
    viewer, vault_dir = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="1:30")
    entry = read_catalog(vault_dir)["episodes"][0]
    assert list(entry["title"]) == [V1_EPOCH_ISO]
    assert V1_EPOCH not in entry["title"]


# Spec: v1 `source_id` conversion | Same rules as `migrate` command
def test_the_v1_source_id_becomes_a_source_url(legacy_v1):
    viewer, vault_dir = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="1:30")
    catalog = read_catalog(vault_dir)
    assert catalog["source"] == V1_SOURCE_TEMPLATE.format("chan-1")
    assert "source_id" not in catalog


# Spec: Request URL category | `entries` (v1 category name)
# Spec: Entry lookup | Find entry by `id` in the v1 `entries` array
def test_the_request_targets_the_pre_migration_category(legacy_v1):
    viewer, vault_dir = legacy_v1
    assert viewer.send("POST", V1_ROUTE, {"title": "Chorus", "timecode": "90"}).status_code in (
        302,
        303,
    )
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Chorus"]


# Spec: Post-migration location | Entry is in `episodes` after migration
def test_the_entry_ends_up_in_episodes(legacy_v1):
    viewer, vault_dir = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="90")
    catalog = read_catalog(vault_dir)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1"]
    assert "entries" not in catalog


# Spec: Redirect after success | Redirect uses post-migration category (`episodes`)
def test_the_redirect_uses_the_post_migration_category(legacy_v1):
    viewer, _ = legacy_v1
    path, query = location(create(viewer, V1_ROUTE, title="Chorus", timecode="1:30"))
    assert path == V3_ROUTE
    assert query == {"timecode": ["90"]}


# Spec: Subsequent requests | Must use `episodes`
def test_a_second_annotation_goes_through_the_episodes_route(legacy_v1):
    viewer, vault_dir = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="90")
    create(viewer, V3_ROUTE, title="Outro", timecode="200")
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Chorus", "Outro"]


# Spec: Post auto-migration viewer routing | valid categories become `episodes`,
# `streams`, `clips`
def test_the_migrated_vault_serves_the_v3_categories(legacy_v1):
    viewer, _ = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="90")
    for category in ("episodes", "streams", "clips"):
        assert viewer.get(f"/catalog/vault/{category}").status_code == 200


# Spec: Post auto-migration viewer routing | v1 `entries` category is no longer valid
# Spec: Retired GET behavior | ... may redirect to canonical v3 viewer routes or return `404`
def test_the_v1_entries_route_is_retired(legacy_v1):
    viewer, _ = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="90")
    response = viewer.get(V1_ROUTE)
    assert response.status_code in (302, 303, 404)
    if response.status_code in (302, 303):
        assert is_redirect(response, "/catalog/vault/episodes")


# Spec: Post auto-migration viewer routing | ... (the migrated entry still serves)
def test_the_migrated_entry_page_serves_from_episodes(legacy_v1):
    viewer, _ = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="90")
    response = viewer.get(V3_ROUTE)
    assert response.status_code == 200
    assert "Chorus" in response.text


# Spec: Pristine v1 and v2 catalogs do not define `annotations`. As a result,
# `PATCH`/`DELETE` on legacy vaults are only meaningful after auto-migration
def test_update_on_a_pristine_v1_vault_finds_no_annotation(legacy_v1):
    viewer, vault_dir = legacy_v1
    assert viewer.send("PATCH", V1_ROUTE, {"id": "a1", "title": "Bridge"}).status_code == 404
    assert read_catalog(vault_dir)["version"] == 1


# Spec: ... such as after a prior successful `POST` in the same migrated vault
def test_update_works_after_a_prior_create_migrated_the_vault(legacy_v1):
    viewer, vault_dir = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="90")
    annotation_id = stored_annotations(vault_dir, "episodes", "e1")[0]["id"]
    assert viewer.send(
        "PATCH", V3_ROUTE, {"id": annotation_id, "title": "Bridge"}
    ).status_code in (302, 303)
    assert annotation_titles(vault_dir, "episodes", "e1") == ["Bridge"]


# Spec: ... (delete likewise becomes meaningful only after migration)
def test_delete_works_after_a_prior_create_migrated_the_vault(legacy_v1):
    viewer, vault_dir = legacy_v1
    create(viewer, V1_ROUTE, title="Chorus", timecode="90")
    annotation_id = stored_annotations(vault_dir, "episodes", "e1")[0]["id"]
    viewer.send("DELETE", V3_ROUTE, {"id": annotation_id})
    assert stored_annotations(vault_dir, "episodes", "e1") == []


# Spec: Post-migration location | ... (a v2 category other than episodes stays put)
def test_a_v2_clip_annotation_stays_in_clips(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v2_catalog(clips=[v2_entry("c1", stamp=V2_STAMP)]))
    route = entry_route("vault", "clips", "c1")
    path, _ = location(create(serve(), route, title="Chorus", timecode="90"))
    assert path == route
    assert annotation_titles(vault_dir, "clips", "c1") == ["Chorus"]
