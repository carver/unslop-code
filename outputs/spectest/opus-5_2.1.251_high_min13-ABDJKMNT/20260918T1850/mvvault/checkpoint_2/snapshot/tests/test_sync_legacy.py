"""Spec section: `sync` on Legacy Vaults."""

import pytest
import responses

from conftest import (
    V1_SOURCE_TEMPLATE,
    latest,
    payload,
    read_backup,
    read_catalog,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)

from mvaultlib.commands import sync_vault


@pytest.fixture
def mocked_source(tmp_path, monkeypatch):
    """Run `sync` in-process against a mocked HTTP source, from inside `tmp_path`.

    The derived v1 source URL is a fixed public host, so it cannot be pointed at
    the local test server the way a v2/v3 `source` can.
    """
    monkeypatch.chdir(tmp_path)
    with responses.RequestsMock() as mock:
        yield mock


# Spec: Source URL for v1 | Derive from `source_id` using the standard derivation
def test_sync_requests_the_derived_v1_url(mocked_source, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")], source_id="chan-1"))
    mocked_source.get(V1_SOURCE_TEMPLATE.format("chan-1"), json=payload())

    sync_vault("vault")
    assert mocked_source.calls[0].request.url == V1_SOURCE_TEMPLATE.format("chan-1")


# Spec: v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3 catalog to disk
def test_sync_on_v1_writes_a_v3_catalog_with_updates(mocked_source, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    mocked_source.get(
        V1_SOURCE_TEMPLATE.format("chan-1"),
        json=payload(episodes=[source_entry("e1", title="updated")]),
    )

    sync_vault("vault")
    catalog = read_catalog(tmp_path / "vault")
    assert catalog["version"] == 3
    assert latest(catalog["episodes"][0]["title"]) == "updated"


# Spec: Backup before write | ... backup contains the **original** pre-migration catalog
def test_sync_on_v1_backs_up_the_original_catalog(mocked_source, tmp_path):
    original = v1_catalog(entries=[v1_entry("e1")])
    write_vault(tmp_path, original)
    mocked_source.get(V1_SOURCE_TEMPLATE.format("chan-1"), json=payload())

    sync_vault("vault")
    assert read_backup(tmp_path / "vault") == original


# Spec: v2 vault | Auto-migrate to v3 in memory, apply sync updates, write v3 catalog to disk
def test_sync_on_v2_writes_a_v3_catalog_with_updates(run, tmp_path, source):
    directory = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=source.url))
    source.serve(payload(episodes=[source_entry("e1", title="updated")]))

    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(directory)
    assert catalog["version"] == 3
    assert latest(catalog["episodes"][0]["title"]) == "updated"


# Spec: Backup before write | Standard backup rules apply; backup contains the **original**
# pre-migration catalog
def test_sync_on_v2_backs_up_the_original_catalog(run, tmp_path, source):
    original = v2_catalog(episodes=[v2_entry("e1")], source=source.url)
    directory = write_vault(tmp_path, original)
    source.serve(payload(episodes=[source_entry("e1")]))

    run("sync", "vault")
    assert read_backup(directory) == original


# Spec: v2 vault | ... apply sync updates (an entry the source dropped is marked removed)
def test_sync_on_v2_marks_missing_entries_removed(run, tmp_path, source):
    directory = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=source.url))
    source.serve(payload())

    run("sync", "vault")
    assert latest(read_catalog(directory)["episodes"][0]["removed"]) is True


# Spec: v2 vault | ... (migration-added `removed: false` is not re-appended by the sync)
def test_sync_on_v2_keeps_one_removed_entry_for_a_still_present_entry(run, tmp_path, source):
    directory = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=source.url))
    source.serve(payload(episodes=[source_entry("e1")]))

    run("sync", "vault")
    assert list(read_catalog(directory)["episodes"][0]["removed"].values()) == [False]


# Spec: v3 vault | Normal sync behavior
def test_sync_on_v3_is_unchanged(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    assert run("sync", "vault").returncode == 0
    assert read_catalog(vault)["version"] == 3


# Spec: v2 vault | ... (sync timestamps stay strictly later than migrated history keys)
def test_sync_timestamp_follows_the_migration_timestamp(run, tmp_path, source):
    directory = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=source.url))
    source.serve(payload(episodes=[source_entry("e1", title="updated")]))

    run("sync", "vault")
    entry = read_catalog(directory)["episodes"][0]
    assert max(entry["title"]) > max(entry["removed"])
