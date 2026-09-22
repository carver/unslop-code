"""Spec section: Multi-Version Loading / `sync` on Legacy Vaults / Migration Persistence."""

import json

from conftest import (
    EPOCH_KEY,
    ISO_KEY,
    current,
    find_entry,
    legacy_entry,
    read_catalog,
    source_entry,
    v1_catalog,
    v2_catalog,
    write_vault,
)


def sync(run_cli, name="legacy"):
    result = run_cli("sync", name)
    assert result.returncode == 0, result.stderr


# Phrase: "v2 vault | Auto-migrate to v3 in memory, apply sync updates, write v3 catalog to disk"
def test_sync_of_v2_vault_writes_a_v3_catalog(run_cli, source, tmp_path):
    vault = write_vault(tmp_path, "legacy", v2_catalog(source.url, episodes=[legacy_entry("e1", ISO_KEY)]))
    source.serve(episodes=[source_entry("e1", title="updated")])
    sync(run_cli)

    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    entry = find_entry(catalog, "episodes", "e1")
    assert current(entry["title"]) == "updated"
    assert entry["annotations"] == []
    assert current(entry["removed"]) is False


# Phrase: "Auto-migrate to v3 in memory, apply sync updates" - legacy history is kept, not replaced
def test_sync_of_v2_vault_keeps_legacy_history(run_cli, source, tmp_path):
    entry = legacy_entry("e1", ISO_KEY, title={"2024-06-15T09:40:00": "original"})
    vault = write_vault(tmp_path, "legacy", v2_catalog(source.url, episodes=[entry]))
    source.serve(episodes=[source_entry("e1", title="changed")])
    sync(run_cli)

    title = find_entry(read_catalog(vault), "episodes", "e1")["title"]
    assert title["2024-06-15T09:40:00"] == "original"
    assert current(title) == "changed"


# Phrase: "Entries created by `sync` | Written in v3 shape, with `annotations` as `[]`"
def test_entries_created_by_sync_have_empty_annotations(run_cli, source, vault):
    source.serve(episodes=[source_entry("fresh")])
    sync(run_cli, "demo")
    assert find_entry(read_catalog(vault), "episodes", "fresh")["annotations"] == []


# Phrase: "Entries created by `sync` | Written in v3 shape" - also in a migrated legacy vault
def test_sync_adds_new_entries_to_a_migrated_v2_vault(run_cli, source, tmp_path):
    vault = write_vault(tmp_path, "legacy", v2_catalog(source.url, episodes=[legacy_entry("e1", ISO_KEY)]))
    source.serve(episodes=[source_entry("e1"), source_entry("e2")])
    sync(run_cli)

    new_entry = find_entry(read_catalog(vault), "episodes", "e2")
    assert new_entry["annotations"] == []
    assert list(new_entry["removed"].values()) == [False]


# Phrase: "Backup before write | ... backup contains the **original** pre-migration catalog"
def test_backup_after_legacy_sync_is_the_pre_migration_catalog(run_cli, source, tmp_path):
    original = v2_catalog(source.url, episodes=[legacy_entry("e1", ISO_KEY)])
    vault = write_vault(tmp_path, "legacy", original)
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)

    assert json.loads((vault / "catalog.bak").read_text()) == original


# Phrase: "v3 vault | Normal sync behavior"
def test_sync_of_v3_vault_is_unchanged(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", views=3)])
    sync(run_cli, "demo")
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert current(find_entry(catalog, "episodes", "e1")["views"]) == 3


# Phrase: "Read-only access | Loading a v1 or v2 catalog for a read-only operation does not rewrite `catalog.json`"
def test_failed_sync_of_a_legacy_vault_rewrites_nothing(run_cli, source, tmp_path):
    original = v2_catalog(source.url, episodes=[legacy_entry("e1", ISO_KEY)])
    vault = write_vault(tmp_path, "legacy", original)
    source.raw_body = b"not json"

    result = run_cli("sync", "legacy")
    assert result.returncode != 0
    assert json.loads((vault / "catalog.json").read_text()) == original
    assert not (vault / "catalog.bak").exists()


# Phrase: "Source URL for v1 | Derive from `source_id` using the standard derivation"
def test_sync_of_a_v1_vault_never_uses_source_id_verbatim(run_cli, source, tmp_path):
    write_vault(tmp_path, "legacy", v1_catalog(legacy_entry("e1", EPOCH_KEY), source_id="chan7"))
    result = run_cli("sync", "legacy")
    assert result.returncode != 0
    assert source.requests == 0


# Phrase: "Save timing | Save migrated v3 catalog immediately"
def test_migrated_catalog_is_saved_by_the_migrate_command(run_cli, tmp_path):
    vault = write_vault(tmp_path, "legacy", v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    run_cli("migrate", "legacy")
    assert read_catalog(vault)["version"] == 3


# Phrase: "v3 reload | No additional history entry, no semantic modification, no backup write"
def test_reloading_a_v3_vault_adds_no_history(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli, "demo")
    before = find_entry(read_catalog(vault), "episodes", "e1")

    run_cli("migrate", "demo")
    after = find_entry(read_catalog(vault), "episodes", "e1")
    assert after == before


# Phrase: "In-memory representation | All versions are usable by every command"
def test_sync_after_migrate_matches_sync_straight_from_v2(run_cli, source, tmp_path):
    for name in ("direct", "premigrated"):
        write_vault(tmp_path, name, v2_catalog(source.url, episodes=[legacy_entry("e1", ISO_KEY)]))
    run_cli("migrate", "premigrated")
    source.serve(episodes=[source_entry("e1", title="same")])
    sync(run_cli, "direct")
    sync(run_cli, "premigrated")

    direct = find_entry(read_catalog(tmp_path / "direct"), "episodes", "e1")
    premigrated = find_entry(read_catalog(tmp_path / "premigrated"), "episodes", "e1")
    assert current(direct["title"]) == current(premigrated["title"]) == "same"
    assert list(direct["title"].values()) == list(premigrated["title"].values())
