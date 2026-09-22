"""`sync` on Legacy Vaults and Migration Persistence through `sync`."""

import json
from datetime import datetime

import pytest

from conftest import (
    EPOCH_KEY,
    EPOCH_KEY_ISO,
    V1_SOURCE_URL,
    current,
    read_catalog,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
)
from mvaultlib import source as source_module
from mvaultlib import sync as sync_module


@pytest.fixture
def sync_v1(monkeypatch, tmp_path):
    """Run a sync in-process against a stubbed source, recording the URL used."""
    monkeypatch.chdir(tmp_path)
    requested = []

    def run(name="v", episodes=(), streams=(), clips=()):
        def fetch(url):
            requested.append(url)
            return {"episodes": list(episodes), "streams": list(streams), "clips": list(clips)}

        monkeypatch.setattr(source_module, "fetch", fetch)
        sync_module.sync(name, datetime.now())
        return requested[-1]

    return run


# Spec: v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3
# catalog to disk
def test_sync_on_v1_vault_writes_a_v3_catalog(sync_v1, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    sync_v1(episodes=[source_entry("a", views=99)])
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Spec: Source URL for v1 | Derive from `source_id` using the standard derivation
def test_sync_on_v1_vault_fetches_the_derived_source(sync_v1, make_vault):
    make_vault(v1_catalog([v1_entry("a")]))
    assert sync_v1(episodes=[source_entry("a")]) == V1_SOURCE_URL


# Spec: v1 vault | ... apply sync updates (the migrated history is extended)
def test_sync_on_v1_vault_appends_to_migrated_history(sync_v1, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a", views={EPOCH_KEY: 10})]))
    sync_v1(episodes=[source_entry("a", views=42)])
    views = read_catalog(vault)["episodes"][0]["views"]
    assert views[EPOCH_KEY_ISO] == 10
    assert current(views) == 42


# Spec: v1 vault | ... write v3 catalog to disk (migrated entries keep `removed`)
def test_sync_on_v1_vault_keeps_the_migration_removed_entry(sync_v1, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    sync_v1(episodes=[source_entry("a")])
    entry = read_catalog(vault)["episodes"][0]
    assert current(entry["removed"]) is False
    assert entry["annotations"] == []


# Spec: v1 vault | ... apply sync updates (an entry gone from the source is removed)
def test_sync_on_v1_vault_marks_missing_entries_removed(sync_v1, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    sync_v1(episodes=[])
    assert current(read_catalog(vault)["episodes"][0]["removed"]) is True


# Spec: Backup before write | backup contains the original pre-migration catalog
def test_sync_on_v1_vault_backs_up_the_pre_migration_catalog(sync_v1, make_vault):
    original = v1_catalog([v1_entry("a")])
    vault = make_vault(original)
    sync_v1(episodes=[source_entry("a")])
    assert json.loads((vault / "catalog.bak").read_text()) == original


# Spec: v2 vault | Auto-migrate to v3 in memory, apply sync updates, write v3
# catalog to disk
def test_sync_on_v2_vault_writes_a_v3_catalog(run_cli, make_vault, source):
    vault = make_vault(v2_catalog(source.url, episodes=[v2_entry("a")]))
    source.payload = {"episodes": [source_entry("a", title="new")], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert current(catalog["episodes"][0]["title"]) == "new"


# Spec: v2 vault | ... (the existing source URL is the one that is fetched)
def test_sync_on_v2_vault_uses_the_catalog_source(run_cli, make_vault, source):
    make_vault(v2_catalog(source.url))
    assert run_cli("sync", "v").returncode == 0
    assert source.requests == 1


# Spec: Backup before write | Standard backup rules apply; backup contains the
# original pre-migration catalog
def test_sync_on_v2_vault_backs_up_the_pre_migration_catalog(run_cli, make_vault, source):
    original = v2_catalog(source.url, clips=[v2_entry("c")])
    vault = make_vault(original)
    assert run_cli("sync", "v").returncode == 0
    assert json.loads((vault / "catalog.bak").read_text()) == original


# Spec: v2 vault | ... every migrated entry gains `removed` and `annotations`
def test_sync_on_v2_vault_migrates_every_category(run_cli, make_vault, source):
    vault = make_vault(
        v2_catalog(source.url, episodes=[v2_entry("e")], streams=[v2_entry("s")], clips=[v2_entry("c")])
    )
    assert run_cli("sync", "v").returncode == 0
    catalog = read_catalog(vault)
    for name in ("episodes", "streams", "clips"):
        assert catalog[name][0]["annotations"] == []
        assert list(catalog[name][0]["removed"].values()) == [False, True]


# Spec: v3 vault | Normal sync behavior
def test_sync_on_v3_vault_is_unaffected(run_cli, vault, source):
    source.payload = {"episodes": [source_entry("a")], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    assert read_catalog(vault)["episodes"][0]["id"] == "a"


# Spec: Trigger | `migrate` command or `sync` on a v1/v2 vault (a failed sync
# migrates nothing)
def test_failed_sync_on_legacy_vault_leaves_the_catalog_unchanged(run_cli, make_vault, source):
    vault = make_vault(v2_catalog(source.url, episodes=[v2_entry("a")]))
    before = (vault / "catalog.json").read_bytes()
    source.status = 500
    assert run_cli("sync", "v").returncode != 0
    assert (vault / "catalog.json").read_bytes() == before
    assert not (vault / "catalog.bak").exists()


# Spec: Post-migration usability | All subsequent commands operate as for a
# vault created in v3
def test_second_sync_after_legacy_sync_is_native(run_cli, make_vault, source):
    vault = make_vault(v2_catalog(source.url, episodes=[v2_entry("a")]))
    source.payload = {"episodes": [source_entry("a", views=1)], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    migrated = (vault / "catalog.json").read_bytes()
    source.payload = {"episodes": [source_entry("a", views=2)], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    assert (vault / "catalog.bak").read_bytes() == migrated
    assert current(read_catalog(vault)["episodes"][0]["views"]) == 2
