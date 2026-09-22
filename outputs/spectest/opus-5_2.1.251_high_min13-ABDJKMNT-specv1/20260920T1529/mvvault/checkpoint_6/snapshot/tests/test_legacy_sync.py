"""Spec section: `sync` on Legacy Vaults."""

import pytest

from mvaultlib import sync as sync_module
from mvaultlib.sync import sync_vault

from conftest import (
    V1_KEY,
    V2_KEY,
    entry_by_id,
    payload,
    read_backup,
    read_catalog,
    run_cli,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)


@pytest.fixture
def offline_source(monkeypatch):
    """Replaces the HTTP fetch, recording the URL `sync` decided to read.

    A v1 vault derives an unreachable `media.example.com` URL, so testing the
    sync itself means standing in for the fetch.
    """

    fetched = {}

    def fetch(url):
        fetched["url"] = url
        return fetched["payload"]

    fetched["payload"] = payload()
    monkeypatch.setattr(sync_module, "fetch_source", fetch)
    return fetched


def sync_offline(vault, offline_source, **categories):
    offline_source["payload"] = payload(**categories)
    sync_vault(str(vault))
    return read_catalog(vault)


# `sync` on Legacy Vaults: "v1 vault | Auto-migrate to v3 in memory, apply sync
# updates, write v3 catalog to disk".
def test_sync_migrates_a_v1_vault_and_writes_v3(tmp_path, offline_source):
    vault = write_vault(tmp_path, v1_catalog([v1_entry("e1")]))
    catalog = sync_offline(vault, offline_source, episodes=[source_entry("e1", title="fresh")])
    entry = entry_by_id(catalog, "episodes", "e1")

    assert catalog["version"] == 3
    assert entry["title"]["2024-06-15T09:40:00"] == "title-e1"
    assert entry["title"][max(entry["title"])] == "fresh"


# `sync` on Legacy Vaults: "Source URL for v1 | Derive from `source_id` using
# the standard derivation".
def test_sync_of_a_v1_vault_fetches_the_derived_url(tmp_path, offline_source):
    vault = write_vault(tmp_path, v1_catalog([v1_entry("e1")], source_id="chan-7"))
    sync_offline(vault, offline_source, episodes=[source_entry("e1")])

    assert offline_source["url"] == "https://media.example.com/channel/chan-7"
    assert read_catalog(vault)["source"] == "https://media.example.com/channel/chan-7"


# `sync` on Legacy Vaults: "v1 vault | ... apply sync updates" — an entry the
# source no longer lists is marked removed, which needs the `removed` history
# the migration added.
def test_sync_of_a_v1_vault_can_remove_a_migrated_entry(tmp_path, offline_source):
    vault = write_vault(tmp_path, v1_catalog([v1_entry("gone")]))
    catalog = sync_offline(vault, offline_source)
    removed = entry_by_id(catalog, "episodes", "gone")["removed"]

    assert removed[max(removed)] is True
    assert list(removed.values()) == [False, True]


# `sync` on Legacy Vaults: "v2 vault | Auto-migrate to v3 in memory, apply sync
# updates, write v3 catalog to disk".
def test_sync_migrates_a_v2_vault_and_writes_v3(tmp_path, source):
    vault = write_vault(tmp_path, v2_catalog(source.url, streams=[v2_entry("s1")]))
    source.serve(payload(streams=[source_entry("s1", views=99)]))

    assert run_cli("sync", "demo", cwd=tmp_path).returncode == 0
    catalog = read_catalog(vault)
    entry = entry_by_id(catalog, "streams", "s1")

    assert catalog["version"] == 3
    assert entry["views"][V2_KEY] == 10
    assert entry["views"][max(entry["views"])] == 99
    assert entry["annotations"] == []


# `sync` on Legacy Vaults: "v3 vault | Normal sync behavior" — a vault already
# in the native format syncs without a migration step.
def test_sync_of_a_v3_vault_is_unchanged(vault, source):
    source.serve(payload(clips=[source_entry("c1")]))
    assert run_cli("sync", "demo", cwd=vault.parent).returncode == 0
    assert read_catalog(vault)["version"] == 3


# `sync` on Legacy Vaults: "Entries created by `sync` | Written in v3 shape,
# with `annotations` as `[]`".
def test_entries_created_by_sync_carry_annotations(vault, source):
    source.serve(payload(episodes=[source_entry("e1")]))
    assert run_cli("sync", "demo", cwd=vault.parent).returncode == 0

    entry = entry_by_id(read_catalog(vault), "episodes", "e1")
    assert entry["annotations"] == []
    assert set(entry) == {
        "id", "published", "width", "height", "annotations",
        "title", "description", "views", "likes", "preview", "removed",
    }


# `sync` on Legacy Vaults: "Entries created by `sync` | Written in v3 shape" —
# including entries added to a vault that was v1 a moment earlier.
def test_new_entries_on_a_migrated_vault_are_v3_shaped(tmp_path, offline_source):
    vault = write_vault(tmp_path, v1_catalog([v1_entry("old")]))
    catalog = sync_offline(vault, offline_source, episodes=[source_entry("new")])

    assert entry_by_id(catalog, "episodes", "new")["annotations"] == []
    assert entry_by_id(catalog, "episodes", "old")["annotations"] == []


# `sync` on Legacy Vaults: "Backup before write | Standard backup rules apply;
# backup contains the **original** pre-migration catalog".
def test_sync_backs_up_the_pre_migration_catalog(tmp_path, source):
    original = v2_catalog(source.url, [v2_entry("e1")])
    vault = write_vault(tmp_path, original)
    source.serve(payload(episodes=[source_entry("e1")]))

    assert run_cli("sync", "demo", cwd=tmp_path).returncode == 0
    assert read_backup(vault) == original


# `sync` on Legacy Vaults: the same rule for v1, whose backup keeps the flat
# `entries` list and the epoch history keys.
def test_v1_sync_backup_keeps_the_legacy_shape(tmp_path, offline_source):
    original = v1_catalog([v1_entry("e1")])
    vault = write_vault(tmp_path, original)
    sync_offline(vault, offline_source, episodes=[source_entry("e1")])

    backup = read_backup(vault)
    assert backup == original
    assert list(backup["entries"][0]["title"]) == [V1_KEY]
