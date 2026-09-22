"""Spec section: `sync` on Legacy Vaults (+ Migration Persistence via `sync`)."""

from __future__ import annotations

import json
from pathlib import Path

CATEGORIES = ("episodes", "streams", "clips")


def catalog_path(workdir, name="vault"):
    return Path(workdir) / name / "catalog.json"


def backup_path(workdir, name="vault"):
    return Path(workdir) / name / "catalog.bak"


# Spec: | v2 vault | Auto-migrate to v3 in memory, apply sync updates, write v3
#       catalog to disk |
def test_sync_v2_writes_v3_catalog(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert catalog["version"] == 3
    assert helpers.find_entry(catalog, "e1")["annotations"] == []


# Spec: | v2 vault | ... apply sync updates ... |
# Context: a changed tracked value appends history on top of the migrated entry.
def test_sync_v2_applies_updates_to_migrated_entry(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=4242)]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["views"][legacy.V2_STAMP] == 100
    assert helpers.current(entry["views"]) == 4242
    assert len(entry["views"]) == 2


# Spec: | v2 vault | ... | Context: an entry the source no longer lists is
# marked removed on top of the migration-added `removed` history.
def test_sync_v2_marks_missing_entry_removed(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("gone")]))
    source.set(helpers.make_payload(episodes=[]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "gone")
    assert helpers.current(entry["removed"]) is True
    assert list(entry["removed"].values()) == [False, True]


# Spec: | v3 vault | Normal sync behavior |
def test_sync_v3_normal_behavior(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert catalog["version"] == 3
    assert helpers.find_entry(catalog, "e1") is not None


# Spec: | Entries created by `sync` | Written in v3 shape, with `annotations` as `[]` |
def test_sync_created_entries_have_empty_annotations(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["annotations"] == []


# Spec: | Entries created by `sync` | Written in **v3 shape** ... |
# Context: v3 shape = static fields, the five tracked histories, `removed`
# history and `annotations`.
def test_sync_created_entries_have_v3_shape(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in ("id", "published", "width", "height"):
        assert field in entry
    for field in ("title", "description", "views", "likes", "preview", "removed"):
        assert isinstance(entry[field], dict)
    assert entry["annotations"] == []


# Spec: | Entries created by `sync` | Written in v3 shape, with `annotations` as `[]` |
# Context: also for an entry newly seen while syncing a legacy vault.
def test_sync_on_v2_creates_v3_shaped_entries(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("e1"), helpers.make_source_entry("new")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "new")
    assert entry["annotations"] == []
    assert list(entry["removed"].values()) == [False]


# Spec: | Source URL for v1 | Derive from `source_id` using the standard derivation |
def test_sync_v1_fetches_the_derived_url(run_cli, make_vault, legacy):
    make_vault(legacy.v1_catalog(source_id="alpha", entries=[legacy.v1_entry("e1")]))
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert legacy.v1_source("alpha") in result.stderr


# Spec: | Source URL for v1 | Derive from `source_id` ... |
# Context: the vault's own `source`-less catalog is never asked for a `source`
# key; a v1 catalog that also carries an unrelated `source_id` shape stays v1.
def test_sync_v1_does_not_contact_the_local_server(run_cli, make_vault, legacy, source):
    make_vault(legacy.v1_catalog(source_id="alpha", entries=[legacy.v1_entry("e1")]))
    assert run_cli("sync", "vault").returncode != 0
    assert source.requests == []


# Spec: | Backup before write | Standard backup rules apply; backup contains the
#       **original** pre-migration catalog |
def test_sync_v2_backup_holds_original_pre_migration_catalog(run_cli, make_vault, legacy, source, helpers, workdir):
    original = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")])
    make_vault(original)
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=7)]))
    assert run_cli("sync", "vault").returncode == 0
    backup = json.loads(backup_path(workdir).read_text(encoding="utf-8"))
    assert backup == original
    assert backup["version"] == 2


# Spec: | Backup before write | Standard backup rules apply ... |
# Context: the migrated catalog is what ends up in `catalog.json`.
def test_sync_v2_catalog_and_backup_differ(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    assert json.loads(catalog_path(workdir).read_text(encoding="utf-8"))["version"] == 3
    assert json.loads(backup_path(workdir).read_text(encoding="utf-8"))["version"] == 2


# Spec: | v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3
#       catalog to disk |
# Context: the derived v1 source is unreachable from the tests, so the observable
# rule here is that a failed fetch leaves the legacy catalog untouched - the
# migration is in memory only until the successful write. See AMBIGUITIES.md T17.
def test_sync_v1_failed_fetch_leaves_v1_catalog(run_cli, make_vault, legacy, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    before = catalog_path(workdir).read_text(encoding="utf-8")
    assert run_cli("sync", "vault").returncode != 0
    assert catalog_path(workdir).read_text(encoding="utf-8") == before
    assert not backup_path(workdir).exists()


# Spec: | v2 vault | Auto-migrate to v3 in memory, apply sync updates, ... |
# Context: sorting and every other v3 sync rule apply to the migrated catalog.
def test_sync_v2_orders_entries_like_v3(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[
        legacy.v2_entry("old", published="2023-01-01T00:00:00"),
        legacy.v2_entry("new", published="2025-01-01T00:00:00"),
    ]))
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("old", published="2023-01-01T00:00:00"),
        helpers.make_source_entry("new", published="2025-01-01T00:00:00"),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["new", "old"]


# Spec: | v2 vault | ... | Context: a second sync of the now-v3 vault is an
# ordinary v3 sync and no longer re-migrates.
def test_second_sync_after_legacy_sync_is_native(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    first = helpers.read_catalog(workdir)
    assert run_cli("sync", "vault").returncode == 0
    second = helpers.read_catalog(workdir)
    assert second == first
    assert json.loads(backup_path(workdir).read_text(encoding="utf-8"))["version"] == 3
