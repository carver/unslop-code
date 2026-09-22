"""Spec sections: `sync` on Legacy Vaults, Migration Determinism."""
import json
import os
import re

import pytest

from conftest import (
    EPOCH_TO_ISO,
    LEGACY_SOURCE_PREFIX,
    all_entries,
    backup_path,
    catalog_text,
    current,
    entry,
    find,
    payload,
    read_backup,
    read_catalog,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    write_vault,
)

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


# ---------------------------------------------------------------------------
# `sync` on Legacy Vaults
# ---------------------------------------------------------------------------

# --- Phrase: "| v2 vault | Auto-migrate to v3 in memory, apply sync updates,
#     write v3 catalog to disk |"
def test_sync_on_v2_writes_a_v3_catalog(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("a")]))
    source.set_payload(payload(episodes=[entry("a")]))
    result = run("sync", "vault")
    assert result.returncode == 0, result
    catalog = read_catalog(tmp_path)
    assert catalog["version"] == 3
    assert catalog["source"] == source.url


def test_sync_on_v2_applies_updates(run, source, tmp_path):
    write_vault(
        tmp_path,
        v2_catalog(
            source=source.url,
            episodes=[v2_entry("a", stamp="2020-01-01T00:00:00")],
        ),
    )
    source.set_payload(payload(episodes=[entry("a", title="changed")]))
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert current(stored, "title") == "changed"
    assert len(stored["title"]) == 2


def test_sync_on_v2_adds_removed_and_annotations(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("a")]))
    source.set_payload(payload(episodes=[entry("a")]))
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert current(stored, "removed") is False
    assert stored["annotations"] == []


def test_sync_on_v2_marks_entries_absent_from_source_removed(
    run, source, tmp_path
):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("gone")]))
    source.set_payload(payload())
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert current(stored, "removed") is True
    # migration wrote `false`, the sync appended `true`
    assert len(stored["removed"]) == 2


def test_sync_on_v2_adds_new_entries(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("old")]))
    source.set_payload(payload(episodes=[entry("old"), entry("new")]))
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert {e["id"] for e in catalog["episodes"]} == {"old", "new"}


# --- Phrase: "| v1 vault | Auto-migrate to v3 in memory, apply sync updates,
#     write v3 catalog to disk |" and "| Source URL for v1 | Derive from
#     `source_id` using the standard derivation |"
def test_sync_on_v1_fetches_the_derived_url(run, tmp_path):
    write_vault(tmp_path, v1_catalog(source_id="derived-1",
                                     entries=[v1_entry("a")]))
    result = run("sync", "vault")
    # The derived host is not resolvable from the test environment, so the run
    # fails at the fetch -- the message proves which URL was used.
    assert result.returncode != 0, result
    assert LEGACY_SOURCE_PREFIX + "derived-1" in result.stderr, result


def test_sync_on_v1_with_unreachable_source_leaves_catalog_v1(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a")]))
    before = catalog_text(tmp_path)
    assert run("sync", "vault").returncode != 0
    assert catalog_text(tmp_path) == before
    assert not os.path.exists(backup_path(tmp_path))


# --- Phrase: "| v3 vault | Normal sync behavior |"
def test_sync_on_v3_is_unchanged(run, source, tmp_path):
    write_vault(tmp_path, v3_catalog(source=source.url))
    source.set_payload(payload(episodes=[entry("a")]))
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert catalog["version"] == 3
    assert [e["id"] for e in catalog["episodes"]] == ["a"]


# --- Phrase: "| Backup before write | Standard backup rules apply; backup
#     contains the **original** pre-migration catalog |"
def test_sync_backup_holds_the_original_v2_catalog(run, source, tmp_path):
    original = v2_catalog(source=source.url, episodes=[v2_entry("a")])
    write_vault(tmp_path, original)
    source.set_payload(payload(episodes=[entry("a", title="changed")]))
    assert run("sync", "vault").returncode == 0
    assert read_backup(tmp_path) == original


def test_sync_backup_is_not_the_intermediate_v3_catalog(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("a")]))
    source.set_payload(payload(episodes=[entry("a")]))
    assert run("sync", "vault").returncode == 0
    backup = read_backup(tmp_path)
    assert backup["version"] == 2
    assert "removed" not in backup["episodes"][0]
    assert "annotations" not in backup["episodes"][0]


# ---------------------------------------------------------------------------
# Migration Determinism
# ---------------------------------------------------------------------------

# --- Phrase: "| Migration-added `removed` value | Single history entry with
#     value `false` |"
@pytest.mark.parametrize("version", [1, 2])
def test_migration_removed_is_a_single_false_entry(run, tmp_path, version):
    catalog = (v1_catalog(entries=[v1_entry("a"), v1_entry("b")])
               if version == 1
               else v2_catalog(episodes=[v2_entry("a")],
                               streams=[v2_entry("b")]))
    write_vault(tmp_path, catalog)
    assert run("migrate", "vault").returncode == 0
    for stored in all_entries(read_catalog(tmp_path)):
        assert list(stored["removed"].values()) == [False]


# --- Phrase: "| Migration-added timestamp scope | Each migration-added
#     `removed` timestamp must be ISO 8601; cross-entry equality is not
#     required |"
def test_migration_removed_timestamps_are_iso_8601(run, tmp_path):
    write_vault(
        tmp_path,
        v1_catalog(entries=[v1_entry("a"), v1_entry("b"), v1_entry("c")]),
    )
    assert run("migrate", "vault").returncode == 0
    for stored in all_entries(read_catalog(tmp_path)):
        for key in stored["removed"]:
            assert ISO.match(key), key


# --- Phrase: "| v1 UNIX-epoch conversion | Convert each epoch-seconds key to
#     `YYYY-MM-DDTHH:MM:SS` in UTC |"
@pytest.mark.parametrize("epoch,iso", sorted(EPOCH_TO_ISO.items()))
def test_v1_epoch_keys_convert_to_utc_iso(run, tmp_path, epoch, iso):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a", stamp=epoch)]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert list(stored["title"]) == [iso]


# --- Phrase: "| v1 category target | Every migrated entry goes to `episodes` |"
def test_every_v1_entry_lands_in_episodes(run, tmp_path):
    write_vault(
        tmp_path, v1_catalog(entries=[v1_entry("a"), v1_entry("b")])
    )
    assert run("migrate", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert len(catalog["episodes"]) == 2
    assert catalog["streams"] == [] and catalog["clips"] == []


# --- Phrase: "| v1 `source_id` conversion |
#     `https://media.example.com/channel/<source_id>` |"
@pytest.mark.parametrize("source_id", ["a", "chan-1", "UPPER_case.9"])
def test_v1_source_derivation_is_deterministic(run, tmp_path, source_id):
    write_vault(tmp_path, v1_catalog(source_id=source_id))
    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path)["source"] == LEGACY_SOURCE_PREFIX + source_id


# --- Phrase: "| v3 reload | No additional history entry, no semantic
#     modification, no backup write |"
def test_v3_reload_adds_no_history_and_no_backup(run, source, tmp_path):
    write_vault(tmp_path, v3_catalog(source=source.url))
    source.set_payload(payload(episodes=[entry("a")]))
    assert run("sync", "vault").returncode == 0
    first = read_catalog(tmp_path)
    counts = {f: len(first["episodes"][0][f])
              for f in ("title", "description", "views", "likes", "preview",
                        "removed")}
    os.remove(backup_path(tmp_path))
    assert run("migrate", "vault").returncode == 0
    second = read_catalog(tmp_path)
    assert second == first
    assert {f: len(second["episodes"][0][f]) for f in counts} == counts
    assert not os.path.exists(backup_path(tmp_path))


# --- Phrase: "| Idempotence | Re-loading already migrated v3 catalog produces
#     no further effects |"
def test_migration_is_idempotent(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a")]))
    assert run("migrate", "vault").returncode == 0
    once = read_catalog(tmp_path)
    assert run("migrate", "vault").returncode == 0
    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path) == once


def test_repeated_migrate_keeps_the_original_backup(run, tmp_path):
    original = v1_catalog(entries=[v1_entry("a")])
    write_vault(tmp_path, original)
    assert run("migrate", "vault").returncode == 0
    assert run("migrate", "vault").returncode == 0
    assert read_backup(tmp_path) == original
