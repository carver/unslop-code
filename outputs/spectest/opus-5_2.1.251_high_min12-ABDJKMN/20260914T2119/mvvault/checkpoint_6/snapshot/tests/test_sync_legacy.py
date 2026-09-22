"""Spec: `sync` on Legacy Vaults (and the matching Migration Persistence rows)."""
import json
import os

import pytest

from conftest import (ISO_A, TS_RE, V1_SOURCE_PREFIX, backup_path,
                      catalog_bytes, current, find_entry, make_entry,
                      make_v1_catalog, make_v1_entry, make_v2_catalog,
                      make_v2_entry, make_v3_catalog, make_v3_entry,
                      read_catalog, read_json, sorted_keys)


@pytest.fixture
def v2_vault(make_vault, source):
    """A v2 vault whose preserved `source` points at the local test server."""

    def _make(episodes=None, streams=(), clips=()):
        catalog = make_v2_catalog(
            source=source.url,
            episodes=[make_v2_entry(id="e1")] if episodes is None else episodes,
            streams=streams, clips=clips)
        make_vault(catalog)
        return catalog

    return _make


# Spec: "| v2 vault | Auto-migrate to v3 in memory, apply sync updates, write v3
# catalog to disk |" -- the catalog on disk is v3 afterwards.
def test_sync_on_v2_writes_v3_catalog(run, source, tmp_path, v2_vault):
    v2_vault()
    source.serve(episodes=[make_entry(id="e1")])
    assert run("sync", "vault").returncode == 0
    assert read_catalog(tmp_path)["version"] == 3


# Spec: "v2 vault | Auto-migrate to v3 in memory, ..." -- the migrated entry
# gains the v3-only fields.
def test_sync_on_v2_adds_v3_entry_fields(run, source, tmp_path, v2_vault):
    v2_vault()
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(entry["removed"]) is False
    assert entry["annotations"] == []


# Spec: "v2 vault | ... **apply sync updates** ..." -- a changed tracked value
# is appended on top of the migrated history.
def test_sync_on_v2_applies_updates(run, source, tmp_path, v2_vault):
    v2_vault(episodes=[make_v2_entry(id="e1", title={ISO_A: "Old"})])
    source.serve(episodes=[make_entry(id="e1", title="New")])
    run("sync", "vault")
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert entry["title"][ISO_A] == "Old"
    assert current(entry["title"]) == "New"
    assert len(entry["title"]) == 2


# Spec: "v2 vault | ... apply sync updates ..." -- a new source entry is added
# to the migrated catalog.
def test_sync_on_v2_adds_new_entries(run, source, tmp_path, v2_vault):
    v2_vault()
    source.serve(episodes=[make_entry(id="e1"), make_entry(id="e2")])
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert {e["id"] for e in catalog["episodes"]} == {"e1", "e2"}


# Spec: "v2 vault | ... apply sync updates ..." -- an entry absent from the
# source is marked removed, on top of the migration-added `false`.
def test_sync_on_v2_marks_absent_entry_removed(run, source, tmp_path, v2_vault):
    v2_vault()
    source.serve(episodes=[])
    run("sync", "vault")
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(entry["removed"]) is True
    assert entry["removed"][sorted_keys(entry["removed"])[0]] is False


# Spec: "| Backup before write | Standard backup rules apply; backup contains
# the **original** pre-migration catalog |"
def test_sync_on_v2_backs_up_the_pre_migration_catalog(run, source, tmp_path,
                                                       v2_vault):
    original = v2_vault()
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    assert read_json(backup_path(tmp_path)) == original


# Spec: "Backup before write | Standard backup rules apply ..." -- exactly one
# backup is written, so it is not the just-migrated catalog.
def test_sync_on_v2_backup_is_not_the_migrated_catalog(run, source, tmp_path,
                                                       v2_vault):
    v2_vault()
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    assert read_json(backup_path(tmp_path))["version"] == 2
    assert read_catalog(tmp_path)["version"] == 3


# Spec: "| v3 vault | Normal sync behavior |"
def test_sync_on_v3_behaves_normally(run, source, tmp_path, make_vault):
    make_vault(make_v3_catalog(source=source.url,
                               episodes=[make_v3_entry(id="e1")]))
    source.serve(episodes=[make_entry(id="e1", title="Changed")])
    assert run("sync", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(entry["title"]) == "Changed"
    assert read_catalog(tmp_path)["version"] == 3


# Spec: "| Source URL for v1 | Derive from `source_id` using the standard
# derivation |" -- the derived URL is what sync tries to reach.
def test_sync_on_v1_targets_the_derived_url(run, make_vault):
    make_vault(make_v1_catalog(source_id="derive-me"))
    res = run("sync", "vault")
    assert res.returncode != 0
    assert V1_SOURCE_PREFIX + "derive-me" in res.stderr


# Spec: "v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3
# catalog to disk" -- a sync that cannot reach its source writes nothing, so
# the v1 catalog is still on disk untouched.
def test_failed_sync_on_v1_leaves_catalog_untouched(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(source_id="unreachable-host-id"))
    before = catalog_bytes(tmp_path)
    assert run("sync", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before
    assert read_catalog(tmp_path)["version"] == 1


# Spec: "| Trigger | `migrate` command or `sync` on a v1/v2 vault |" -- the
# in-memory migration performed by a read-only command is not persisted, but a
# sync's is.
def test_sync_persists_the_migration(run, source, tmp_path, v2_vault):
    v2_vault()
    assert run("digest", "vault").returncode == 0
    assert read_catalog(tmp_path)["version"] == 2

    source.serve(episodes=[make_entry(id="e1")])
    assert run("sync", "vault").returncode == 0
    assert read_catalog(tmp_path)["version"] == 3


# Spec: "| Post-migration usability | All subsequent commands operate as for a
# vault created in v3 |" -- a second sync behaves like any v3 sync.
def test_second_sync_after_auto_migration(run, source, tmp_path, v2_vault):
    v2_vault()
    source.serve(episodes=[make_entry(id="e1", views=10)])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", views=99)])
    assert run("sync", "vault").returncode == 0

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(entry["views"]) == 99
    assert read_json(backup_path(tmp_path))["version"] == 3


# Spec: "v2 vault | Auto-migrate to v3 in memory ..." -- every category of the
# migrated catalog stays usable by sync.
def test_sync_on_v2_handles_all_categories(run, source, tmp_path, v2_vault):
    v2_vault(episodes=[make_v2_entry(id="e1")],
             streams=[make_v2_entry(id="s1")],
             clips=[make_v2_entry(id="c1")])
    source.serve(episodes=[make_entry(id="e1")],
                 streams=[make_entry(id="s1", title="Live")],
                 clips=[make_entry(id="c1")])
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert current(find_entry(catalog, "streams", "s1")["title"]) == "Live"
    assert current(find_entry(catalog, "clips", "c1")["removed"]) is False
