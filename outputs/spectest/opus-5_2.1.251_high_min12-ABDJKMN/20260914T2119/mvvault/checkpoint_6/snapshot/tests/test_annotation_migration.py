"""Spec: Annotation Auto-Migration, its rules, and the category transition."""
import os

import pytest

from annotation_helpers import (assert_clean, backup_file, create, created_id,
                                mutate, only_annotation, redirect_path,
                                redirect_timecode, remove, stored_annotations,
                                stored_backup, stored_catalog, update)
from conftest import read_catalog
from digest_helpers import E1, E2, K1, legacy_entry, v1, v1_entry, v2, v3, v3_entry

V1_SOURCE = "https://media.example.com/channel/chan42"


def removed_keys(catalog):
    """Every history key of every migration-added `removed` field."""
    keys = []
    for category in ("episodes", "streams", "clips"):
        for entry in catalog.get(category, []):
            keys.extend(entry.get("removed", {}).keys())
    return keys


def strip_volatile(catalog):
    """A catalog with the migration timestamps and annotations normalised."""
    import copy
    clone = copy.deepcopy(catalog)
    for category in ("episodes", "streams", "clips"):
        for entry in clone.get(category, []):
            entry["removed"] = {"STAMP": list(entry.get("removed", {}).values())}
            entry.pop("annotations", None)
    return clone


# --------------------------------------------------------------------------
# Vault version behaviour table
# --------------------------------------------------------------------------
# Spec: "| v1 | Migrate entire catalog to v3 first, then apply annotation,
# then persist |"
def test_v1_annotation_migrates_the_catalog(serve, tmp_path, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    response = create(serve(), title="Note", timecode="90",
                      category="entries")
    assert response.is_redirect, response
    assert stored_catalog(tmp_path)["version"] == 3


# Spec: "| v1 | Migrate ... then apply annotation, then persist |"
def test_v1_annotation_is_applied(serve, tmp_path, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    create(serve(), title="Migrated note", timecode="1:30",
           category="entries")
    stored = stored_annotations(tmp_path, category="episodes")
    assert [item["title"] for item in stored] == ["Migrated note"]
    assert stored[0]["timecode"] == 90


# Spec: "| v2 | Migrate entire catalog to v3 first, then apply annotation,
# then persist |"
def test_v2_annotation_migrates_the_catalog(serve, tmp_path, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    response = create(serve(), title="Note", timecode="90")
    assert response.is_redirect, response
    assert stored_catalog(tmp_path)["version"] == 3


# Spec: "| v2 | Migrate ... then apply annotation, then persist |"
def test_v2_annotation_is_applied(serve, tmp_path, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    create(serve(), title="V2 note", timecode="42")
    assert [item["title"] for item in stored_annotations(tmp_path)] == [
        "V2 note"]


# Spec: "| v3 | Apply annotation directly |" -- no version churn.
def test_v3_annotation_is_applied_directly(serve, tmp_path, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    create(serve(), title="Note", timecode="90")
    assert stored_catalog(tmp_path)["version"] == 3


# Spec: "Annotation mutations (create, update, delete) require version 3
# format because the `annotations` field does not exist in v1 or v2 entries."
# -- after the mutation, every migrated entry has the field.
def test_every_migrated_entry_gains_the_annotations_field(serve, tmp_path,
                                                          make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1"), legacy_entry(id="e2")],
                  clips=[legacy_entry(id="c1")]))
    create(serve(), title="Note", timecode="90")
    catalog = stored_catalog(tmp_path)
    for category in ("episodes", "clips"):
        for entry in catalog[category]:
            assert isinstance(entry["annotations"], list)


# --------------------------------------------------------------------------
# Auto-Migration Rules
# --------------------------------------------------------------------------
# Spec: "| Migration scope | Full catalog migration (same rules as `migrate`
# command) |" -- an untouched category is migrated too.
def test_migration_covers_the_whole_catalog(serve, tmp_path, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")],
                  streams=[legacy_entry(id="s1")],
                  clips=[legacy_entry(id="c1")]))
    create(serve(), title="Note", timecode="90")
    catalog = stored_catalog(tmp_path)
    assert [entry["id"] for entry in catalog["streams"]] == ["s1"]
    assert "removed" in catalog["streams"][0]
    assert "removed" in catalog["clips"][0]


# Spec: "| Migration scope | Full catalog migration (same rules as `migrate`
# command) |" -- the auto-migrated file matches what `migrate` produces.
@pytest.mark.parametrize("builder,entries", [
    (v1, {"entries": [v1_entry(id="e1"), v1_entry(id="e2")]}),
    (v2, {"episodes": [legacy_entry(id="e1")],
          "clips": [legacy_entry(id="c1")]}),
])
def test_auto_migration_matches_the_migrate_command(serve, run, tmp_path,
                                                    make_vault, builder,
                                                    entries):
    make_vault(builder(**entries), name="auto")
    make_vault(builder(**entries), name="manual")
    category = "entries" if builder is v1 else "episodes"
    create(serve(), title="Note", timecode="90", name="auto",
           category=category)
    assert run("migrate", "manual").returncode == 0
    assert strip_volatile(read_catalog(tmp_path, "auto")) == \
        strip_volatile(read_catalog(tmp_path, "manual"))


# Spec: "| Backup before migration | `catalog.bak` contains the original
# pre-migration catalog |"
def test_backup_holds_the_original_v1_catalog(serve, tmp_path, make_vault):
    original = v1(entries=[v1_entry(id="e1")])
    make_vault(original)
    create(serve(), title="Note", timecode="90", category="entries")
    assert stored_backup(tmp_path) == original


# Spec: "| Backup before migration | `catalog.bak` contains the original
# pre-migration catalog |" -- v2.
def test_backup_holds_the_original_v2_catalog(serve, tmp_path, make_vault):
    original = v2(episodes=[legacy_entry(id="e1")])
    make_vault(original)
    create(serve(), title="Note", timecode="90")
    assert stored_backup(tmp_path) == original


# Spec: "| Single write for migration + annotation | Migration and annotation
# may be persisted in one write; backup must reflect state before **both**
# changes |" -- the backup has neither the migration nor the annotation.
def test_backup_precedes_both_changes(serve, tmp_path, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    create(serve(), title="Note", timecode="90", category="entries")
    backup = stored_backup(tmp_path)
    assert backup["version"] == 1
    assert "episodes" not in backup
    assert "annotations" not in backup["entries"][0]


# Spec: "| Single write for migration + annotation | ... |" -- the persisted
# catalog carries both changes at once.
def test_single_write_carries_both_changes(serve, tmp_path, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    create(serve(), title="Note", timecode="90", category="entries")
    catalog = stored_catalog(tmp_path)
    assert catalog["version"] == 3
    assert len(catalog["episodes"][0]["annotations"]) == 1


# Spec: "| v1 UNIX-epoch key conversion | Same rules as `migrate` command |"
def test_v1_epoch_keys_are_converted(serve, tmp_path, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    create(serve(), title="Note", timecode="90", category="entries")
    entry = stored_catalog(tmp_path)["episodes"][0]
    assert list(entry["title"]) == [K1]
    assert E1 not in entry["title"]


# Spec: "| v1 `source_id` conversion | Same rules as `migrate` command |"
def test_v1_source_id_is_converted(serve, tmp_path, make_vault):
    make_vault(v1(source_id="chan42", entries=[v1_entry(id="e1")]))
    create(serve(), title="Note", timecode="90", category="entries")
    catalog = stored_catalog(tmp_path)
    assert catalog["source"] == V1_SOURCE
    assert "source_id" not in catalog


# Spec: "| Auto-migration timestamp | Same timestamp used for all
# migration-added `removed` fields |"
def test_migration_removed_stamps_are_identical(serve, tmp_path, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1"), legacy_entry(id="e2")],
                  streams=[legacy_entry(id="s1")],
                  clips=[legacy_entry(id="c1")]))
    create(serve(), title="Note", timecode="90")
    keys = removed_keys(stored_catalog(tmp_path))
    assert len(keys) == 4
    assert len(set(keys)) == 1


# Spec: "| Post auto-migration viewer routing | Vault now serves as v3; valid
# categories become `episodes`, `streams`, `clips` ... |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_categories_are_served_after_auto_migration(serve, make_vault,
                                                       category):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    server = serve()
    create(server, title="Note", timecode="90", category="entries")
    response = server.get("/catalog/vault/%s" % category)
    assert response.status == 200, response


# Spec: "| Post auto-migration viewer routing | ... v1 `entries` category is
# no longer valid |"
def test_v1_entries_category_is_retired(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    server = serve()
    assert server.get("/catalog/vault/entries").status == 200
    create(server, title="Note", timecode="90", category="entries")
    after = server.get("/catalog/vault/entries")
    assert after.status in (302, 303, 404), after
    if after.is_redirect:
        assert after.location == "/catalog/vault/episodes"
    assert_clean(after)


# Spec: "| Retired GET behavior | Later `GET` requests to the retired v1
# `entries` route may redirect to canonical v3 viewer routes or return
# `404` |" -- the entry-level route too.
def test_retired_v1_entry_route(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    server = serve()
    create(server, title="Note", timecode="90", category="entries")
    after = server.get("/catalog/vault/entries/e1")
    assert after.status in (302, 303, 404), after
    assert_clean(after)


# Spec: "| Post auto-migration viewer routing | Vault now serves as v3 ... |"
# -- the vault's default route follows the new version.
def test_default_route_follows_the_new_version(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    server = serve()
    create(server, title="Note", timecode="90", category="entries")
    response = server.get("/catalog/vault")
    assert response.is_redirect, response
    assert response.location == "/catalog/vault/episodes"


# --------------------------------------------------------------------------
# Auto-Migration -- Category Transition
# --------------------------------------------------------------------------
# Spec: "| Request URL category | `entries` (v1 category name) |" and
# "| Entry lookup | Find entry by `id` in the v1 `entries` array |"
def test_request_targets_the_pre_migration_category(serve, tmp_path,
                                                    make_vault):
    make_vault(v1(entries=[v1_entry(id="e1"), v1_entry(id="e2")]))
    response = create(serve(), title="Second", timecode="90",
                      category="entries", entry_id="e2")
    assert response.is_redirect, response
    assert stored_annotations(tmp_path, category="episodes",
                              entry_id="e1") == []
    assert len(stored_annotations(tmp_path, category="episodes",
                                  entry_id="e2")) == 1


# Spec: "| Post-migration location | Entry is in `episodes` after migration |"
def test_entry_moves_to_episodes(serve, tmp_path, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    create(serve(), title="Note", timecode="90", category="entries")
    catalog = stored_catalog(tmp_path)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1"]
    assert "entries" not in catalog


# Spec: "| Redirect after success | Redirect uses post-migration category
# (`episodes`) |" and Determinism: "| Redirect after v1 annotation | Uses
# `episodes`, not `entries` |"
def test_redirect_uses_the_post_migration_category(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    response = create(serve(), title="Note", timecode="1:30",
                      category="entries")
    assert redirect_path(response) == "/catalog/vault/episodes/e1"
    assert "/entries/" not in (response.location or "")
    assert redirect_timecode(response) == "90"


# Spec: "| Determinism | Post auto-migration category | v1 entries always
# migrate to `episodes` |" -- never streams or clips.
def test_v1_entries_never_land_in_other_categories(serve, tmp_path,
                                                   make_vault):
    make_vault(v1(entries=[v1_entry(id="e1"), v1_entry(id="e2")]))
    create(serve(), title="Note", timecode="90", category="entries")
    catalog = stored_catalog(tmp_path)
    assert len(catalog["episodes"]) == 2
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# Spec: "| Subsequent requests | Must use `episodes` (v1 `entries` route is
# retired after migration) |" -- a second annotation goes through `episodes`.
def test_second_annotation_uses_episodes(serve, tmp_path, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    server = serve()
    create(server, title="first", timecode="1", category="entries")
    response = create(server, title="second", timecode="2",
                      category="episodes")
    assert response.is_redirect, response
    assert [item["title"] for item in
            stored_annotations(tmp_path, category="episodes")] == ["first",
                                                                   "second"]


# Spec: "Pristine v1 and v2 catalogs do not define `annotations`. As a
# result, `PATCH`/`DELETE` on legacy vaults are only meaningful after
# auto-migration has produced an entry that already contains annotations,
# such as after a prior successful `POST` in the same migrated vault."
def test_patch_after_auto_migration(serve, tmp_path, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    server = serve()
    annotation_id = created_id(server, tmp_path, title="Before",
                               category="entries",
                               stored_category="episodes")
    response = update(server, id=annotation_id, title="After",
                      category="episodes")
    assert response.is_redirect, response
    assert only_annotation(tmp_path, category="episodes")["title"] == "After"


# Spec: "... `PATCH`/`DELETE` ... only meaningful after auto-migration ..." --
# delete works the same way.
def test_delete_after_auto_migration(serve, tmp_path, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    server = serve()
    annotation_id = created_id(server, tmp_path)
    response = remove(server, id=annotation_id)
    assert response.is_redirect, response
    assert stored_annotations(tmp_path) == []


# Spec: "Pristine v1 and v2 catalogs do not define `annotations`." -- a
# `PATCH` against a pristine legacy vault can only be a not-found.
@pytest.mark.parametrize("builder,category,entries", [
    (v1, "entries", {"entries": [v1_entry(id="e1")]}),
    (v2, "episodes", {"episodes": [legacy_entry(id="e1")]}),
])
def test_patch_on_a_pristine_legacy_vault_is_not_found(serve, make_vault,
                                                       builder, category,
                                                       entries):
    make_vault(builder(**entries))
    response = update(serve(), id="whatever", title="x", category=category)
    assert response.status == 404, response
    assert_clean(response)


# Spec: "Pristine v1 and v2 catalogs do not define `annotations`." -- and so
# can a `DELETE`.
@pytest.mark.parametrize("builder,category,entries", [
    (v1, "entries", {"entries": [v1_entry(id="e1")]}),
    (v2, "episodes", {"episodes": [legacy_entry(id="e1")]}),
])
def test_delete_on_a_pristine_legacy_vault_is_not_found(serve, make_vault,
                                                        builder, category,
                                                        entries):
    make_vault(builder(**entries))
    response = remove(serve(), id="whatever", category=category)
    assert response.status == 404, response
    assert_clean(response)


# Spec: "| Non-existent annotation `id` on update | HTTP `404` |" plus
# "Migration failure ... original catalog unchanged" -- a mutation that never
# succeeds does not rewrite the vault (see AMBIGUITIES T71).
def test_failed_legacy_mutation_leaves_the_catalog_alone(serve, tmp_path,
                                                         make_vault):
    original = v1(entries=[v1_entry(id="e1")])
    make_vault(original)
    remove(serve(), id="nope", category="entries")
    assert stored_catalog(tmp_path) == original
