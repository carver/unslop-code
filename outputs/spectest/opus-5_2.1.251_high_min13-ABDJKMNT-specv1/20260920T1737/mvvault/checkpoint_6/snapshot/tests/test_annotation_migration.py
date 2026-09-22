"""Spec sections: Annotation Auto-Migration, Auto-Migration Rules and
Auto-Migration -- Category Transition."""

import json

import pytest
from annotation_fixtures import (
    V1_ENTRY,
    V3_ENTRY,
    created,
    delete,
    mark,
    patch,
    post,
    stored,
    v1_pair_vault,
)
from conftest import EPOCH_KEY, EPOCH_KEY_AS_ISO, REDIRECT_STATUSES, find_entry, read_catalog
from detail_fixtures import EPOCH_NEW_AS_ISO, MODERN_SOURCE, v1_vault, v2_vault, v3_vault

#: The source URL a v1 `source_id` of `chan42` migrates to.
V1_SOURCE_URL = "https://media.example.com/channel/chan42"

#: Statuses the spec allows for the retired v1 `entries` route after migration.
RETIRED_STATUSES = (302, 303, 404)


# Phrase: "| v1 | Migrate entire catalog to v3 first, then apply annotation,
# then persist |"
def test_a_v1_annotation_migrates_and_then_applies(viewer, tmp_path):
    vault = v1_vault(tmp_path)

    assert post(viewer, path=V1_ENTRY).status in REDIRECT_STATUSES

    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert find_entry(catalog, "episodes", "e1")["annotations"][0]["title"] == "chorus"


# Phrase: "| v2 | Migrate entire catalog to v3 first, then apply annotation,
# then persist |"
def test_a_v2_annotation_migrates_and_then_applies(viewer, tmp_path):
    vault = v2_vault(tmp_path)

    assert post(viewer).status in REDIRECT_STATUSES

    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert find_entry(catalog, "episodes", "e1")["annotations"][0]["title"] == "chorus"


# Phrase: "| v3 | Apply annotation directly |" -- nothing else about the catalog
# changes, and the backup is not a migration snapshot.
def test_a_v3_annotation_is_applied_directly(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    before = read_catalog(vault)

    created(viewer, vault)

    after = read_catalog(vault)
    assert after["version"] == 3
    assert json.loads((vault / "catalog.bak").read_text()) == before
    assert after["clips"] == before["clips"]


# Phrase: "| Migration scope | Full catalog migration (same rules as `migrate`
# command) |" -- the v1 root keys are replaced wholesale.
def test_auto_migration_rewrites_the_whole_v1_catalog(viewer, tmp_path):
    vault = v1_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    catalog = read_catalog(vault)
    assert "source_id" not in catalog
    assert "entries" not in catalog
    assert catalog["streams"] == [] and catalog["clips"] == []


# Phrase: "| Migration scope | Full catalog migration |" -- every migrated entry
# gains the v3 local fields, not just the annotated one.
def test_auto_migration_upgrades_every_entry(viewer, tmp_path):
    vault = v1_pair_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    for entry in read_catalog(vault)["episodes"]:
        assert "removed" in entry and "annotations" in entry


# Phrase: "| Migration scope | Full catalog migration |" -- a v2 vault keeps its
# stored `source` and its category placement.
def test_auto_migration_of_v2_keeps_source_and_categories(viewer, tmp_path):
    vault = v2_vault(tmp_path)

    post(viewer)

    catalog = read_catalog(vault)
    assert catalog["source"] == MODERN_SOURCE
    assert [entry["id"] for entry in catalog["clips"]] == ["c1"]


# Phrase: "| Backup before migration | `catalog.bak` contains the original
# pre-migration catalog |"
@pytest.mark.parametrize("build, path", [(v1_vault, V1_ENTRY), (v2_vault, V3_ENTRY)])
def test_the_backup_is_the_original_pre_migration_catalog(viewer, tmp_path, build, path):
    vault = build(tmp_path)
    original = read_catalog(vault)

    post(viewer, path=path)

    assert json.loads((vault / "catalog.bak").read_text()) == original


# Phrase: "| Backup before annotation | If catalog was already v3, `catalog.bak`
# contains pre-annotation catalog |"
def test_a_v3_backup_holds_the_pre_annotation_catalog(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    before = read_catalog(vault)

    post(viewer)

    assert json.loads((vault / "catalog.bak").read_text()) == before


# Phrase: "| Single write for migration + annotation | ... backup must reflect
# state before **both** changes |"
def test_the_backup_predates_both_the_migration_and_the_annotation(viewer, tmp_path):
    vault = v1_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    backup = json.loads((vault / "catalog.bak").read_text())
    assert backup["version"] == 1
    assert "annotations" not in backup["entries"][0]


# Phrase: "| v1 UNIX-epoch key conversion | Same rules as `migrate` command |"
def test_auto_migration_converts_epoch_history_keys(viewer, tmp_path):
    vault = v1_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    entry = find_entry(read_catalog(vault), "episodes", "e1")
    assert EPOCH_NEW_AS_ISO in entry["title"]


# Phrase: "| v1 `source_id` conversion | Same rules as `migrate` command |"
def test_auto_migration_converts_the_source_id(viewer, tmp_path):
    vault = v1_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    assert read_catalog(vault)["source"] == V1_SOURCE_URL


# Phrase: "| Post auto-migration viewer routing | Vault now serves as v3; valid
# categories become `episodes`, `streams`, `clips` |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_the_migrated_vault_serves_the_v3_categories(viewer, tmp_path, category):
    v1_vault(tmp_path)
    post(viewer, path=V1_ENTRY)

    assert viewer.client.get(f"/catalog/demo/{category}").status == 200


# Phrase: "| Post auto-migration viewer routing | ... v1 `entries` category is no
# longer valid |"
def test_the_entries_category_is_retired_after_migration(viewer, tmp_path):
    v1_vault(tmp_path)
    post(viewer, path=V1_ENTRY)

    assert viewer.client.get("/catalog/demo/entries").status in RETIRED_STATUSES


# Phrase: "| Request URL category | `entries` (v1 category name) |" and
# "| Entry lookup | Find entry by `id` in the v1 `entries` array |"
def test_the_request_targets_the_pre_migration_category(viewer, tmp_path):
    vault = v1_pair_vault(tmp_path)

    assert post(viewer, path="/catalog/demo/entries/e2").status in REDIRECT_STATUSES

    assert stored(vault, "episodes", "e2")[0]["title"] == "chorus"


# Phrase: "| Entry lookup | Find entry by `id` in the v1 `entries` array |" -- an
# id that array does not hold is not found.
def test_an_unknown_v1_id_is_not_found(viewer, tmp_path):
    v1_vault(tmp_path)

    assert post(viewer, path="/catalog/demo/entries/missing").status == 404


# Phrase: "| Post-migration location | Entry is in `episodes` after migration |"
def test_the_annotated_entry_ends_up_in_episodes(viewer, tmp_path):
    vault = v1_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    assert [entry["id"] for entry in read_catalog(vault)["episodes"]] == ["e1"]


# Phrase: "| Redirect after success | Redirect uses post-migration category
# (`episodes`) |"
def test_the_v1_redirect_uses_the_post_migration_category(viewer, tmp_path):
    v1_vault(tmp_path)

    location = post(viewer, path=V1_ENTRY).location

    assert location.endswith(f"{V3_ENTRY}?timecode=90")
    assert "/entries/" not in location


# Phrase: "| Subsequent requests | Must use `episodes` (v1 `entries` route is
# retired after migration) |"
def test_a_second_annotation_uses_the_migrated_category(viewer, tmp_path):
    vault = v1_vault(tmp_path)
    post(viewer, path=V1_ENTRY)

    assert post(viewer, mark(title="second"), path=V3_ENTRY).status in REDIRECT_STATUSES

    assert [note["title"] for note in stored(vault)] == ["chorus", "second"]


# Phrase: "| Subsequent requests | Must use `episodes` ... |" -- the v1 route no
# longer annotates.
def test_the_v1_route_no_longer_annotates_after_migration(viewer, tmp_path):
    vault = v1_vault(tmp_path)
    post(viewer, path=V1_ENTRY)

    assert post(viewer, mark(title="second"), path=V1_ENTRY).status == 404

    assert [note["title"] for note in stored(vault)] == ["chorus"]


# Phrase: "| Retired GET behavior | Later `GET` requests to the retired v1
# `entries` route may redirect to canonical v3 viewer routes or return `404` |"
def test_a_later_get_to_the_retired_route_redirects_or_is_not_found(viewer, tmp_path):
    v1_vault(tmp_path)
    post(viewer, path=V1_ENTRY)

    response = viewer.client.get(V1_ENTRY)

    assert response.status in RETIRED_STATUSES
    if response.status != 404:
        assert viewer.client.follow(V1_ENTRY).status == 200


# Phrase: "Pristine v1 and v2 catalogs do not define `annotations`. As a result,
# `PATCH`/`DELETE` on legacy vaults are only meaningful after auto-migration has
# produced an entry that already contains annotations, such as after a prior
# successful `POST` in the same migrated vault."
def test_patch_and_delete_work_after_a_prior_post_migrated_the_vault(viewer, tmp_path):
    vault = v1_vault(tmp_path)
    post(viewer, path=V1_ENTRY)
    annotation = stored(vault)[0]

    assert patch(viewer, {"id": annotation["id"], "title": "renamed"}).status in REDIRECT_STATUSES
    assert stored(vault)[0]["title"] == "renamed"

    assert delete(viewer, {"id": annotation["id"]}).status in REDIRECT_STATUSES
    assert stored(vault) == []


# Phrase: "Pristine v1 and v2 catalogs do not define `annotations`" -- an update
# against one names an annotation that cannot exist.
@pytest.mark.parametrize("build, path", [(v1_vault, V1_ENTRY), (v2_vault, V3_ENTRY)])
def test_updating_a_pristine_legacy_vault_finds_no_annotation(viewer, tmp_path, build, path):
    build(tmp_path)

    assert patch(viewer, {"id": "whatever", "title": "x"}, path=path).status == 404


# Phrase: "| Auto-migration timestamp | Same timestamp used for all
# migration-added `removed` fields |"
def test_every_migration_added_removed_field_shares_one_timestamp(viewer, tmp_path):
    vault = v1_pair_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    keys = {key for entry in read_catalog(vault)["episodes"] for key in entry["removed"]}
    assert len(keys) == 1


# Phrase: "| v1 UNIX-epoch key conversion | Same rules as `migrate` command |" --
# the shared conftest epoch key converts the same way the `migrate` tests expect.
def test_the_epoch_key_conversion_matches_the_migrate_command(viewer, tmp_path):
    vault = v1_pair_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    assert EPOCH_KEY_AS_ISO in find_entry(read_catalog(vault), "episodes", "e1")["views"]
    assert EPOCH_KEY not in find_entry(read_catalog(vault), "episodes", "e1")["views"]
