"""Spec sections: `migrate` Command, Version 1 to Version 3 Migration,
Version 2 to Version 3 Migration, Migration Persistence."""
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
# `migrate` Command
# ---------------------------------------------------------------------------

# --- Phrase: "| Syntax | `python mvault.py migrate <name>` |"
def test_migrate_subcommand_exists(run, tmp_path):
    write_vault(tmp_path, v3_catalog())
    result = run("migrate", "vault")
    assert result.returncode == 0, result


def test_migrate_requires_a_name(run):
    assert run("migrate").returncode != 0


def test_migrate_is_listed_in_help(run):
    result = run("--help")
    assert "migrate" in result.stdout, result


# --- Phrase: "| Input | Existing vault with v1, v2, or v3 catalog |"
@pytest.mark.parametrize(
    "catalog",
    [
        v1_catalog(entries=[v1_entry("a")]),
        v2_catalog(episodes=[v2_entry("a")]),
        v3_catalog(),
    ],
    ids=["v1", "v2", "v3"],
)
def test_migrate_accepts_every_supported_version(run, tmp_path, catalog):
    write_vault(tmp_path, catalog)
    result = run("migrate", "vault")
    assert result.returncode == 0, result
    assert read_catalog(tmp_path)["version"] == 3


# --- Phrase: "| Effect on v1 or v2 | Convert catalog to v3 on disk |"
@pytest.mark.parametrize("version", [1, 2])
def test_migrate_converts_legacy_catalog_on_disk(run, tmp_path, version):
    catalog = (v1_catalog(entries=[v1_entry("a")]) if version == 1
               else v2_catalog(episodes=[v2_entry("a")]))
    write_vault(tmp_path, catalog)
    assert run("migrate", "vault").returncode == 0
    on_disk = read_catalog(tmp_path)
    assert on_disk["version"] == 3
    assert "source_id" not in on_disk
    assert "entries" not in on_disk


# --- Phrase: "| Effect on v3 | No-op; no backup written |"
def test_migrate_on_v3_writes_no_backup(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[]))
    assert run("migrate", "vault").returncode == 0
    assert not os.path.exists(backup_path(tmp_path))


def test_migrate_on_v3_is_a_no_op(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[]))
    before = catalog_text(tmp_path)
    assert run("migrate", "vault").returncode == 0
    assert catalog_text(tmp_path) == before


# --- Phrase: "| Missing vault | Error to stderr including `<name>`; exit
#     non-zero |"
def test_migrate_missing_vault_errors(run, tmp_path):
    result = run("migrate", "ghost")
    assert result.returncode != 0, result
    assert "ghost" in result.stderr, result


def test_migrate_missing_vault_writes_nothing_to_stdout(run, tmp_path):
    result = run("migrate", "ghost")
    assert "ghost" not in result.stdout, result


# --- Phrase: "| Missing vault | ... |" (context: a directory without a
#     `catalog.json` is not a usable vault either)
def test_migrate_vault_without_catalog_errors(run, tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "vault"))
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert "vault" in result.stderr, result


# ---------------------------------------------------------------------------
# Version 1 to Version 3 Migration
# ---------------------------------------------------------------------------

# --- Phrase: "| `source_id` | Convert to `source` using
#     `https://media.example.com/channel/<source_id>` |"
def test_v1_migration_converts_source_id_to_source(run, tmp_path):
    write_vault(tmp_path, v1_catalog(source_id="chan-42"))
    assert run("migrate", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert catalog["source"] == LEGACY_SOURCE_PREFIX + "chan-42"
    assert "source_id" not in catalog


# --- Phrase: "| Entries | Move every object from `entries` to `episodes` |"
def test_v1_migration_moves_entries_to_episodes(run, tmp_path):
    write_vault(
        tmp_path,
        v1_catalog(entries=[v1_entry("a"), v1_entry("b"), v1_entry("c")]),
    )
    assert run("migrate", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert {e["id"] for e in catalog["episodes"]} == {"a", "b", "c"}
    assert "entries" not in catalog


# --- Phrase: "| Missing categories | Create empty `streams` and `clips`
#     arrays |"
def test_v1_migration_creates_empty_streams_and_clips(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a")]))
    assert run("migrate", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# --- Phrase: "| History keys | Convert every UNIX-epoch string key to ISO 8601
#     format |"
def test_v1_migration_converts_every_history_key(run, tmp_path):
    item = v1_entry("a", stamp="1700000000")
    write_vault(tmp_path, v1_catalog(entries=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    for field in ("title", "description", "views", "likes", "preview"):
        assert list(stored[field]) == [EPOCH_TO_ISO["1700000000"]], field


def test_v1_migration_converts_multiple_keys_per_history(run, tmp_path):
    item = v1_entry(
        "a",
        views={"1700000000": 1, "1718444400": 2, "1718448000": 3},
    )
    write_vault(tmp_path, v1_catalog(entries=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored["views"] == {
        EPOCH_TO_ISO["1700000000"]: 1,
        EPOCH_TO_ISO["1718444400"]: 2,
        EPOCH_TO_ISO["1718448000"]: 3,
    }


# --- Phrase: "| `removed` | Add `{<migration-timestamp>: false}` to every
#     entry |"
def test_v1_migration_adds_removed_history(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a"), v1_entry("b")]))
    assert run("migrate", "vault").returncode == 0
    for stored in read_catalog(tmp_path)["episodes"]:
        assert len(stored["removed"]) == 1
        key, value = next(iter(stored["removed"].items()))
        assert ISO.match(key), key
        assert value is False


# --- Phrase: "| `annotations` | Add `[]` to every entry |"
def test_v1_migration_adds_empty_annotations(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a"), v1_entry("b")]))
    assert run("migrate", "vault").returncode == 0
    for stored in read_catalog(tmp_path)["episodes"]:
        assert stored["annotations"] == []


# --- Phrase: "| Version field | Set `version` to `3` |"
def test_v1_migration_sets_version_three(run, tmp_path):
    write_vault(tmp_path, v1_catalog())
    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path)["version"] == 3


# ---------------------------------------------------------------------------
# Version 2 to Version 3 Migration
# ---------------------------------------------------------------------------

# --- Phrase: "| `source` | Preserve existing value |"
def test_v2_migration_preserves_source(run, tmp_path):
    write_vault(tmp_path, v2_catalog(source="https://keep.test/x.json"))
    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path)["source"] == "https://keep.test/x.json"


# --- Phrase: "| Categories | Preserve `episodes`, `streams`, and `clips`
#     placement |"
def test_v2_migration_preserves_category_placement(run, tmp_path):
    write_vault(
        tmp_path,
        v2_catalog(
            episodes=[v2_entry("e")],
            streams=[v2_entry("s")],
            clips=[v2_entry("c")],
        ),
    )
    assert run("migrate", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["e"]
    assert [e["id"] for e in catalog["streams"]] == ["s"]
    assert [e["id"] for e in catalog["clips"]] == ["c"]


# --- Phrase: "| `removed` | Add `{<migration-timestamp>: false}` to every
#     entry in every category |"
def test_v2_migration_adds_removed_to_every_category(run, tmp_path):
    write_vault(
        tmp_path,
        v2_catalog(
            episodes=[v2_entry("e")],
            streams=[v2_entry("s")],
            clips=[v2_entry("c")],
        ),
    )
    assert run("migrate", "vault").returncode == 0
    entries = all_entries(read_catalog(tmp_path))
    assert len(entries) == 3
    for stored in entries:
        assert len(stored["removed"]) == 1
        key, value = next(iter(stored["removed"].items()))
        assert ISO.match(key), key
        assert value is False


# --- Phrase: "| `annotations` | Add `[]` to every entry |" (context: v2 -> v3)
def test_v2_migration_adds_empty_annotations(run, tmp_path):
    write_vault(
        tmp_path,
        v2_catalog(episodes=[v2_entry("e")], clips=[v2_entry("c")]),
    )
    assert run("migrate", "vault").returncode == 0
    for stored in all_entries(read_catalog(tmp_path)):
        assert stored["annotations"] == []


# --- Phrase: "| Version field | Set `version` to `3` |" (context: v2 -> v3)
def test_v2_migration_sets_version_three(run, tmp_path):
    write_vault(tmp_path, v2_catalog())
    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path)["version"] == 3


# --- Phrase: "| Categories | Preserve ... placement |" (context: v2 history
#     keys are already ISO 8601 and must not be re-keyed)
def test_v2_migration_leaves_history_keys_untouched(run, tmp_path):
    item = v2_entry("a", stamp="2023-01-02T03:04:05")
    write_vault(tmp_path, v2_catalog(episodes=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored["title"] == {"2023-01-02T03:04:05": "Title a"}


# ---------------------------------------------------------------------------
# Migration Persistence
# ---------------------------------------------------------------------------

# --- Phrase: "| Trigger | `migrate` command or `sync` on a v1/v2 vault |"
#     and "| Backup timing | Copy original `catalog.json` to `catalog.bak`
#     before migration write |"
@pytest.mark.parametrize("version", [1, 2])
def test_migrate_writes_a_backup(run, tmp_path, version):
    catalog = (v1_catalog(entries=[v1_entry("a")]) if version == 1
               else v2_catalog(episodes=[v2_entry("a")]))
    write_vault(tmp_path, catalog)
    assert run("migrate", "vault").returncode == 0
    assert os.path.exists(backup_path(tmp_path))


# --- Phrase: "| Backup content | Semantically equivalent pre-migration JSON
#     snapshot |"
@pytest.mark.parametrize("version", [1, 2])
def test_backup_holds_the_pre_migration_catalog(run, tmp_path, version):
    catalog = (v1_catalog(source_id="pre", entries=[v1_entry("a")])
               if version == 1
               else v2_catalog(source="https://pre.test/s.json",
                               episodes=[v2_entry("a")]))
    write_vault(tmp_path, catalog)
    assert run("migrate", "vault").returncode == 0
    assert read_backup(tmp_path) == catalog


# --- Phrase: "| Save timing | Save migrated v3 catalog immediately |"
def test_migrated_catalog_is_saved_immediately(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a")]))
    assert run("migrate", "vault").returncode == 0
    # A second process sees v3 without any further command.
    assert read_catalog(tmp_path)["version"] == 3


# --- Phrase: "| Post-migration usability | All subsequent commands operate as
#     for a vault created in v3 |"
def test_post_migration_sync_behaves_like_native_v3(run, source, tmp_path):
    from conftest import entry, payload

    write_vault(
        tmp_path,
        v2_catalog(source=source.url, episodes=[v2_entry("a", title={})]),
    )
    assert run("migrate", "vault").returncode == 0
    source.set_payload(payload(episodes=[entry("a", title="new")]))
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored["title"][max(stored["title"])] == "new"
    assert stored["removed"][max(stored["removed"])] is False


def test_migrate_twice_is_stable(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a")]))
    assert run("migrate", "vault").returncode == 0
    first = catalog_text(tmp_path)
    assert run("migrate", "vault").returncode == 0
    assert catalog_text(tmp_path) == first


# ---------------------------------------------------------------------------
# Version Handling Errors that apply to migration
# ---------------------------------------------------------------------------

# --- Phrase: "| Failure writing `catalog.bak` | Error to stderr; exit
#     non-zero; abort migration; leave original `catalog.json` intact |"
def test_backup_write_failure_aborts_migration(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a")]))
    before = catalog_text(tmp_path)
    # A directory in the backup's place makes the copy fail.
    os.makedirs(backup_path(tmp_path))
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result
    assert catalog_text(tmp_path) == before
    assert json.loads(before)["version"] == 1


# --- Phrase: "| Malformed v1 or v2 entry data | Error to stderr; exit
#     non-zero; leave `catalog.json` unchanged |"
@pytest.mark.parametrize(
    "item",
    [
        "not-an-object",
        {"id": 5, "published": "2024-01-01T00:00:00", "width": 1, "height": 1,
         "title": {}, "description": {}, "views": {}, "likes": {},
         "preview": {}},
        v1_entry("a", width="wide"),
        v1_entry("a", title="not-a-history-object"),
        v1_entry("a", title={"not-an-epoch": "x"}),
        v1_entry("a", views={"1700000000": "not-an-int"}),
        v1_entry("a", likes={"1700000000": "not-an-int"}),
    ],
    ids=["scalar", "bad-id", "bad-width", "history-not-object", "bad-key",
         "bad-views", "bad-likes"],
)
def test_malformed_v1_entry_errors(run, tmp_path, item):
    write_vault(tmp_path, v1_catalog(entries=[item]))
    before = catalog_text(tmp_path)
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result
    assert catalog_text(tmp_path) == before


@pytest.mark.parametrize(
    "item",
    [
        42,
        v2_entry("a", height=None),
        v2_entry("a", preview={"2024-01-01T00:00:00": 9}),
        v2_entry("a", views={"nonsense": 1}),
    ],
    ids=["scalar", "bad-height", "bad-preview", "bad-key"],
)
def test_malformed_v2_entry_errors(run, tmp_path, item):
    write_vault(tmp_path, v2_catalog(episodes=[item]))
    before = catalog_text(tmp_path)
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert catalog_text(tmp_path) == before


# --- Phrase: "| Malformed v1 or v2 entry data |" (context: a v1 entry missing
#     one of the nine schema fields, see AMBIGUITIES T14)
def test_v1_entry_missing_a_history_field_errors(run, tmp_path):
    item = v1_entry("a")
    del item["likes"]
    write_vault(tmp_path, v1_catalog(entries=[item]))
    result = run("migrate", "vault")
    assert result.returncode != 0, result


# --- Phrase: "| `entries` | array | All entries in a single flat list |"
#     (context: a non-array `entries` is malformed v1 data)
def test_v1_entries_must_be_an_array(run, tmp_path):
    write_vault(tmp_path, {"version": 1, "source_id": "x", "entries": {}})
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result


# --- Phrase: "| `source_id` | string | Short platform identifier |"
def test_v1_source_id_must_be_a_string(run, tmp_path):
    write_vault(tmp_path, {"version": 1, "source_id": 7, "entries": []})
    result = run("migrate", "vault")
    assert result.returncode != 0, result


# --- Phrase: "| `source` | string | Full source URL |" (context: v2)
def test_v2_source_must_be_a_string(run, tmp_path):
    catalog = v2_catalog()
    catalog["source"] = None
    write_vault(tmp_path, catalog)
    result = run("migrate", "vault")
    assert result.returncode != 0, result
