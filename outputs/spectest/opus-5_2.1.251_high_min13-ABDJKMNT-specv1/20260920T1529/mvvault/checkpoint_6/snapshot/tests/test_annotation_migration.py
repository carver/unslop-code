"""Spec sections: Annotation Auto-Migration, the Auto-Migration Rules, the
Auto-Migration category transition, and the determinism rules they carry."""

from conftest import (
    V1_KEY,
    V1_OLDER_KEY,
    V2_KEY,
    entry_by_id,
    read_backup,
    read_catalog,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

SOURCE = "https://example.test/a"
V1_ROUTE = "/catalog/demo/entries/e1"
V3_ROUTE = "/catalog/demo/episodes/e1"
REDIRECTS = (302, 303)

# `upgrade_v1` re-keys epoch history keys through the canonical UTC conversion.
V1_KEY_AS_ISO = "2024-06-15T09:40:00"
V1_OLDER_KEY_AS_ISO = "2023-11-14T22:13:20"


def create(viewer, path, **fields):
    return viewer.send_json("POST", path, fields)


def stored(vault, category="episodes", entry_id="e1"):
    return entry_by_id(read_catalog(vault), category, entry_id)["annotations"]


# Annotation Auto-Migration: "v1 | Migrate entire catalog to v3 first, then apply
# annotation, then persist".
def test_a_v1_annotation_migrates_the_catalog_and_persists_the_annotation(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))

    response = create(viewer, V1_ROUTE, title="a note", timecode="1:30")

    assert response.status in REDIRECTS
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert [note["title"] for note in stored(vault)] == ["a note"]


# Annotation Auto-Migration: "v2 | Migrate entire catalog to v3 first, then apply
# annotation, then persist".
def test_a_v2_annotation_migrates_the_catalog_and_persists_the_annotation(viewer, tmp_path):
    vault = write_vault(tmp_path, v2_catalog(SOURCE, episodes=[v2_entry("e1")]))

    response = create(viewer, V3_ROUTE, title="a note", timecode="30")

    assert response.status in REDIRECTS
    assert read_catalog(vault)["version"] == 3
    assert stored(vault)[0]["timecode"] == 30


# Annotation Auto-Migration: "v3 | Apply annotation directly" — the write leaves
# the version alone and adds no migration timestamps.
def test_a_v3_annotation_is_applied_without_migration(viewer, tmp_path):
    vault = write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("e1")]))

    create(viewer, V3_ROUTE, title="a note", timecode="30")

    entry = entry_by_id(read_catalog(vault), "episodes", "e1")
    assert entry["removed"] == {V2_KEY: False}
    assert len(entry["annotations"]) == 1


# Auto-Migration Rules: "Migration scope | Full catalog migration (same rules as
# `migrate` command)" — every entry gains the v3 fields, not only the annotated
# one.
def test_the_whole_catalog_is_migrated_not_only_the_annotated_entry(viewer, tmp_path):
    vault = write_vault(
        tmp_path,
        v2_catalog(SOURCE, episodes=[v2_entry("e1")], streams=[v2_entry("s1")], clips=[]),
    )

    create(viewer, V3_ROUTE, title="a note", timecode="30")

    catalog = read_catalog(vault)
    for category, entry_id in [("episodes", "e1"), ("streams", "s1")]:
        entry = entry_by_id(catalog, category, entry_id)
        assert entry["removed"] == {max(entry["removed"]): False}
        assert isinstance(entry["annotations"], list)


# Auto-Migration Rules: "Migration scope | Full catalog migration (same rules as
# `migrate` command)" — including the order a migrated catalog is written in.
def test_auto_migration_orders_entries_as_the_migrate_command_does(viewer, tmp_path):
    entries = [
        v1_entry("old", published="2020-01-01T00:00:00"),
        v1_entry("e1", published="2024-12-31T23:59:59"),
        v1_entry("mid", published="2022-06-01T00:00:00"),
    ]
    vault = write_vault(tmp_path, v1_catalog(entries=entries))

    create(viewer, V1_ROUTE, title="a note", timecode="30")

    assert [entry["id"] for entry in read_catalog(vault)["episodes"]] == ["e1", "mid", "old"]


# Auto-Migration Rules: "Backup before migration | `catalog.bak` contains the
# original pre-migration catalog".
def test_the_backup_holds_the_original_pre_migration_catalog(viewer, tmp_path):
    original = v1_catalog(entries=[v1_entry("e1")])
    vault = write_vault(tmp_path, original)

    create(viewer, V1_ROUTE, title="a note", timecode="30")

    assert read_backup(vault) == original


# Auto-Migration Rules: "Backup before annotation | If catalog was already v3,
# `catalog.bak` contains pre-annotation catalog".
def test_the_backup_of_a_v3_vault_holds_the_pre_annotation_catalog(viewer, tmp_path):
    original = v3_catalog(SOURCE, episodes=[v3_entry("e1")])
    vault = write_vault(tmp_path, original)

    create(viewer, V3_ROUTE, title="a note", timecode="30")

    assert read_backup(vault) == original


# Auto-Migration Rules: "Single write for migration + annotation | Migration and
# annotation may be persisted in one write; backup must reflect state before
# **both** changes".
def test_migration_and_annotation_land_in_one_write_behind_one_backup(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))

    create(viewer, V1_ROUTE, title="a note", timecode="30")

    backup = read_backup(vault)
    assert backup["version"] == 1
    assert "annotations" not in backup["entries"][0]
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert stored(vault)[0]["title"] == "a note"


# Auto-Migration Rules: "v1 UNIX-epoch key conversion | Same rules as `migrate`
# command".
def test_v1_epoch_history_keys_are_converted(viewer, tmp_path):
    entry = v1_entry("e1", views={V1_OLDER_KEY: 3, V1_KEY: 9})
    vault = write_vault(tmp_path, v1_catalog(entries=[entry]))

    create(viewer, V1_ROUTE, title="a note", timecode="30")

    migrated = entry_by_id(read_catalog(vault), "episodes", "e1")
    assert migrated["views"] == {V1_OLDER_KEY_AS_ISO: 3, V1_KEY_AS_ISO: 9}
    assert migrated["title"] == {V1_KEY_AS_ISO: "title-e1"}


# Auto-Migration Rules: "v1 `source_id` conversion | Same rules as `migrate`
# command".
def test_v1_source_id_becomes_the_v3_source_url(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")], source_id="chan-7"))

    create(viewer, V1_ROUTE, title="a note", timecode="30")

    catalog = read_catalog(vault)
    assert catalog["source"] == "https://media.example.com/channel/chan-7"
    assert "source_id" not in catalog


# Auto-Migration Rules: "Post auto-migration viewer routing | Vault now serves as
# v3; valid categories become `episodes`, `streams`, `clips`".
def test_the_migrated_vault_serves_the_v3_categories(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    create(viewer, V1_ROUTE, title="a note", timecode="30")

    for category in ("episodes", "streams", "clips"):
        response = viewer.get(f"/catalog/demo/{category}")
        assert response.status == 200, category
    assert viewer.get(V3_ROUTE).status == 200


# Auto-Migration Rules: "Post auto-migration viewer routing | ... v1 `entries`
# category is no longer valid"; Category Transition: "Retired GET behavior |
# Later `GET` requests to the retired v1 `entries` route may redirect to
# canonical v3 viewer routes or return `404`".
def test_the_retired_v1_route_no_longer_serves_the_entry(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    create(viewer, V1_ROUTE, title="a note", timecode="30")

    response = viewer.get(V1_ROUTE)

    if response.status in REDIRECTS:
        assert response.location.startswith("/catalog/demo/episodes")
    else:
        assert response.status == 404


# Category Transition: "Request URL category | `entries` (v1 category name)" and
# "Entry lookup | Find entry by `id` in the v1 `entries` array".
def test_the_annotation_targets_the_entry_through_the_v1_category(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1"), v1_entry("e2")]))

    response = create(viewer, "/catalog/demo/entries/e2", title="on e2", timecode="30")

    assert response.status in REDIRECTS
    assert [note["title"] for note in stored(vault, entry_id="e2")] == ["on e2"]
    assert stored(vault, entry_id="e1") == []


# Category Transition: "Post-migration location | Entry is in `episodes` after
# migration"; Determinism: "Post auto-migration category | v1 entries always
# migrate to `episodes`".
def test_the_annotated_entry_ends_up_in_episodes(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))

    create(viewer, V1_ROUTE, title="a note", timecode="30")

    catalog = read_catalog(vault)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1"]
    assert catalog["streams"] == []
    assert catalog["clips"] == []
    assert "entries" not in catalog


# Category Transition: "Redirect after success | Redirect uses post-migration
# category (`episodes`)"; Determinism: "Redirect after v1 annotation | Uses
# `episodes`, not `entries`".
def test_the_redirect_after_a_v1_annotation_uses_episodes(viewer, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))

    response = create(viewer, V1_ROUTE, title="a note", timecode="1:30")

    assert response.location == f"{V3_ROUTE}?timecode=90"


# Category Transition: "Subsequent requests | Must use `episodes` (v1 `entries`
# route is retired after migration)".
def test_a_second_annotation_must_use_the_migrated_category(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    create(viewer, V1_ROUTE, title="first", timecode="30")

    retired = create(viewer, V1_ROUTE, title="second", timecode="40")

    assert retired.status == 404
    assert [note["title"] for note in stored(vault)] == ["first"]

    accepted = create(viewer, V3_ROUTE, title="second", timecode="40")

    assert accepted.status in REDIRECTS
    assert [note["title"] for note in stored(vault)] == ["first", "second"]


# "Pristine v1 and v2 catalogs do not define `annotations`. As a result,
# `PATCH`/`DELETE` on legacy vaults are only meaningful after auto-migration has
# produced an entry that already contains annotations, such as after a prior
# successful `POST` in the same migrated vault."
def test_update_and_delete_work_after_a_v1_vault_has_been_annotated(viewer, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    create(viewer, V1_ROUTE, title="a note", timecode="30")
    annotation_id = stored(vault)[0]["id"]

    updated = viewer.send_json("PATCH", V3_ROUTE, {"id": annotation_id, "body": "added later"})

    assert updated.status in REDIRECTS
    assert stored(vault)[0]["body"] == "added later"

    deleted = viewer.send_json("DELETE", V3_ROUTE, {"id": annotation_id})

    assert deleted.status in REDIRECTS
    assert stored(vault) == []


# "Pristine v1 and v2 catalogs do not define `annotations`" — a `PATCH` against
# one names an annotation that cannot exist, and nothing is written.
def test_update_on_a_pristine_v1_vault_is_not_found_and_writes_nothing(viewer, tmp_path):
    original = v1_catalog(entries=[v1_entry("e1")])
    vault = write_vault(tmp_path, original)

    response = viewer.send_json("PATCH", V1_ROUTE, {"id": "a1", "title": "renamed"})

    assert response.status == 404
    assert read_catalog(vault) == original
    assert not (vault / "catalog.bak").exists()


# Error Handling: "Migration failure during auto-migration | HTTP `500` with
# error message; original catalog unchanged".
def test_a_failing_migration_answers_500_and_leaves_the_catalog_alone(viewer, tmp_path):
    original = v1_catalog(entries=[v1_entry("e1", key="not-an-epoch")])
    vault = write_vault(tmp_path, original)

    response = create(viewer, V1_ROUTE, title="a note", timecode="30")

    assert response.status == 500
    assert response.body
    assert "Traceback" not in response.body
    assert read_catalog(vault) == original
    assert not (vault / "catalog.bak").exists()


# Error Handling: "Migration failure during auto-migration" — a legacy entry that
# does not match the legacy schema fails the same way.
def test_a_malformed_legacy_entry_fails_the_migration(viewer, tmp_path):
    broken = v1_entry("e1")
    del broken["width"]
    original = v1_catalog(entries=[broken])
    vault = write_vault(tmp_path, original)

    response = create(viewer, V1_ROUTE, title="a note", timecode="30")

    assert response.status == 500
    assert read_catalog(vault) == original


# Determinism: "Auto-migration timestamp | Same timestamp used for all
# migration-added `removed` fields".
def test_every_migration_added_removed_field_shares_one_timestamp(viewer, tmp_path):
    entries = [v1_entry("e1"), v1_entry("e2"), v1_entry("e3")]
    vault = write_vault(tmp_path, v1_catalog(entries=entries))

    create(viewer, V1_ROUTE, title="a note", timecode="30")

    stamps = {tuple(entry["removed"]) for entry in read_catalog(vault)["episodes"]}
    assert len(stamps) == 1
