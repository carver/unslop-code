"""`migrate` Command, the two migration tables and Migration Determinism."""

import json
import re

import pytest

from conftest import (
    EPOCH_KEY,
    EPOCH_KEY_ISO,
    ISO_KEY,
    V1_SOURCE_URL,
    current,
    read_catalog,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
)

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
TRACKED = ["title", "description", "views", "likes", "preview", "removed"]


def migrate(run_cli, name="v"):
    result = run_cli("migrate", name)
    assert result.returncode == 0, result.stderr
    return result


# Spec: Syntax | `python mvault.py migrate <name>`
def test_migrate_is_a_subcommand(run_cli, make_vault):
    make_vault(v1_catalog([v1_entry("a")]))
    assert run_cli("migrate", "v").returncode == 0


# Spec: Syntax | `python mvault.py migrate <name>` (the name is required)
def test_migrate_requires_a_vault_name(run_cli):
    result = run_cli("migrate")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: `python mvault.py --help` | Usage text with available subcommands
def test_help_lists_migrate(run_cli):
    assert "migrate" in run_cli("--help").stdout


# Spec: Missing vault | Error to stderr including `<name>`; exit non-zero
def test_migrate_missing_vault_errors_with_name(run_cli, tmp_path):
    result = run_cli("migrate", "ghost")
    assert result.returncode != 0
    assert "ghost" in result.stderr
    assert not (tmp_path / "ghost").exists()


# Spec: Missing vault | Error to stderr ... (nothing is reported as success)
def test_migrate_missing_vault_prints_nothing_to_stdout(run_cli):
    assert run_cli("migrate", "ghost").stdout == ""


# Spec: Effect on v1 or v2 | Convert catalog to v3 on disk
# Spec: Version field | Set `version` to `3`
@pytest.mark.parametrize(
    "build",
    [lambda: v1_catalog([v1_entry("a")]), lambda: v2_catalog("http://s.invalid/f.json", episodes=[v2_entry("a")])],
)
def test_migrate_writes_version_three(run_cli, make_vault, build):
    vault = make_vault(build())
    migrate(run_cli)
    assert read_catalog(vault)["version"] == 3


# Spec: `source_id` | Convert to `source` using `https://media.example.com/channel/<source_id>`
def test_v1_source_id_becomes_the_derived_source(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    migrate(run_cli)
    catalog = read_catalog(vault)
    assert catalog["source"] == V1_SOURCE_URL
    assert "source_id" not in catalog


# Spec: Entries | Move every object from `entries` to `episodes`
# Spec: v1 category target | Every migrated entry goes to `episodes`
def test_v1_entries_move_to_episodes(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a"), v1_entry("b"), v1_entry("c")]))
    migrate(run_cli)
    catalog = read_catalog(vault)
    assert sorted(entry["id"] for entry in catalog["episodes"]) == ["a", "b", "c"]
    assert "entries" not in catalog


# Spec: Missing categories | Create empty `streams` and `clips` arrays
def test_v1_migration_creates_empty_categories(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    migrate(run_cli)
    catalog = read_catalog(vault)
    assert catalog["streams"] == [] and catalog["clips"] == []


# Spec: History keys | Convert every UNIX-epoch string key to ISO 8601 format
def test_v1_history_keys_are_converted(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a", stamp=EPOCH_KEY)]))
    migrate(run_cli)
    entry = read_catalog(vault)["episodes"][0]
    assert [list(entry[field]) for field in ("title", "description", "views", "likes", "preview")] == [
        [EPOCH_KEY_ISO]
    ] * 5


# Spec: v1 UNIX-epoch conversion | Convert each epoch-seconds key to
# `YYYY-MM-DDTHH:MM:SS` in UTC
@pytest.mark.parametrize(
    "epoch,iso",
    [("0", "1970-01-01T00:00:00"), ("1000000000", "2001-09-09T01:46:40"), ("1718448000", "2024-06-15T10:40:00")],
)
def test_v1_epoch_conversion_is_utc(run_cli, make_vault, epoch, iso):
    vault = make_vault(v1_catalog([v1_entry("a", stamp=epoch)]))
    migrate(run_cli)
    assert list(read_catalog(vault)["episodes"][0]["views"]) == [iso]


# Spec: History keys | Convert every UNIX-epoch string key (values stay attached)
def test_v1_history_values_stay_with_their_keys(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a", views={"0": 1, "1718448000": 2})]))
    migrate(run_cli)
    assert read_catalog(vault)["episodes"][0]["views"] == {"1970-01-01T00:00:00": 1, "2024-06-15T10:40:00": 2}


# Spec: `removed` | Add `{<migration-timestamp>: false}` to every entry
# Spec: Migration-added `removed` value | Single history entry with value `false`
def test_v1_migration_adds_a_single_false_removed_entry(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a"), v1_entry("b")]))
    migrate(run_cli)
    for entry in read_catalog(vault)["episodes"]:
        assert list(entry["removed"].values()) == [False]


# Spec: Migration-added timestamp scope | Each migration-added `removed`
# timestamp must be ISO 8601
def test_migration_removed_timestamp_is_iso(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    migrate(run_cli)
    assert all(ISO.match(key) for key in read_catalog(vault)["episodes"][0]["removed"])


# Spec: `annotations` | Add `[]` to every entry
def test_v1_migration_adds_empty_annotations(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a"), v1_entry("b")]))
    migrate(run_cli)
    assert [entry["annotations"] for entry in read_catalog(vault)["episodes"]] == [[], []]


# Spec: `source` | Preserve existing value
def test_v2_source_is_preserved(run_cli, make_vault):
    vault = make_vault(v2_catalog("https://kept.invalid/feed.json", episodes=[v2_entry("a")]))
    migrate(run_cli)
    assert read_catalog(vault)["source"] == "https://kept.invalid/feed.json"


# Spec: Categories | Preserve `episodes`, `streams`, and `clips` placement
def test_v2_categories_keep_their_entries(run_cli, make_vault):
    vault = make_vault(
        v2_catalog("http://s.invalid/f.json", episodes=[v2_entry("e")], streams=[v2_entry("s")], clips=[v2_entry("c")])
    )
    migrate(run_cli)
    catalog = read_catalog(vault)
    assert [[entry["id"] for entry in catalog[name]] for name in ("episodes", "streams", "clips")] == [["e"], ["s"], ["c"]]


# Spec: `removed` | Add `{<migration-timestamp>: false}` to every entry in every category
def test_v2_migration_adds_removed_in_every_category(run_cli, make_vault):
    vault = make_vault(
        v2_catalog("http://s.invalid/f.json", episodes=[v2_entry("e")], streams=[v2_entry("s")], clips=[v2_entry("c")])
    )
    migrate(run_cli)
    catalog = read_catalog(vault)
    for name in ("episodes", "streams", "clips"):
        assert list(catalog[name][0]["removed"].values()) == [False]


# Spec: `annotations` | Add `[]` to every entry (v2)
def test_v2_migration_adds_empty_annotations(run_cli, make_vault):
    vault = make_vault(v2_catalog("http://s.invalid/f.json", clips=[v2_entry("c")]))
    migrate(run_cli)
    assert read_catalog(vault)["clips"][0]["annotations"] == []


# Spec: Version 2 Entry Schema | ISO 8601 string keys (migration keeps them)
def test_v2_history_keys_survive_migration(run_cli, make_vault):
    vault = make_vault(v2_catalog("http://s.invalid/f.json", episodes=[v2_entry("a", stamp=ISO_KEY)]))
    migrate(run_cli)
    entry = read_catalog(vault)["episodes"][0]
    assert list(entry["title"]) == [ISO_KEY]
    assert entry["title"][ISO_KEY] == "title-a"


# Spec: Backup timing | Copy original `catalog.json` to `catalog.bak` before migration write
# Spec: Backup content | Semantically equivalent pre-migration JSON snapshot
@pytest.mark.parametrize(
    "build",
    [lambda: v1_catalog([v1_entry("a")]), lambda: v2_catalog("http://s.invalid/f.json", streams=[v2_entry("a")])],
)
def test_migration_backs_up_the_pre_migration_catalog(run_cli, make_vault, build):
    original = build()
    vault = make_vault(original)
    migrate(run_cli)
    assert json.loads((vault / "catalog.bak").read_text()) == original


# Spec: Save timing | Save migrated v3 catalog immediately
def test_migrated_catalog_is_on_disk_after_the_command(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    migrate(run_cli)
    catalog = read_catalog(vault)
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Spec: Effect on v3 | No-op; no backup written
def test_migrate_on_v3_writes_no_backup(run_cli, vault):
    before = (vault / "catalog.json").read_bytes()
    migrate(run_cli)
    assert not (vault / "catalog.bak").exists()
    assert (vault / "catalog.json").read_bytes() == before


# Spec: v3 reload | No additional history entry, no semantic modification, no backup write
def test_migrate_on_synced_v3_vault_changes_nothing(run_cli, vault, source):
    source.payload = {"episodes": [source_entry("a")], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    before = (vault / "catalog.json").read_bytes()
    backup_before = (vault / "catalog.bak").read_bytes()
    migrate(run_cli)
    assert (vault / "catalog.json").read_bytes() == before
    assert (vault / "catalog.bak").read_bytes() == backup_before


# Spec: Idempotence | Re-loading already migrated v3 catalog produces no further effects
def test_migrate_is_idempotent(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    migrate(run_cli)
    after_first = (vault / "catalog.json").read_bytes()
    backup_after_first = (vault / "catalog.bak").read_bytes()
    migrate(run_cli)
    assert (vault / "catalog.json").read_bytes() == after_first
    assert (vault / "catalog.bak").read_bytes() == backup_after_first


# Spec: Post-migration usability | All subsequent commands operate as for a vault
# created in v3
def test_sync_after_migrate_behaves_natively(run_cli, make_vault, source):
    vault = make_vault(v2_catalog(source.url, episodes=[v2_entry("a")]))
    migrate(run_cli)
    source.payload = {"episodes": [source_entry("a", title="fresh")], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    entry = read_catalog(vault)["episodes"][0]
    assert current(entry["title"]) == "fresh"
    assert len(entry["title"]) == 2


# Spec: Failure writing `catalog.bak` | Error to stderr; exit non-zero; abort
# migration; leave original `catalog.json` intact
def test_backup_write_failure_aborts_the_migration(run_cli, make_vault):
    vault = make_vault(v1_catalog([v1_entry("a")]))
    before = (vault / "catalog.json").read_bytes()
    (vault / "catalog.bak").mkdir()
    result = run_cli("migrate", "v")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert (vault / "catalog.json").read_bytes() == before


# Spec: `catalog.json` Ordering applies to the migrated file (AMBIGUITIES T14)
def test_migrated_entries_follow_catalog_ordering(run_cli, make_vault):
    entries = [
        v1_entry("old", published="2020-01-01T00:00:00"),
        v1_entry("new", published="2024-01-01T00:00:00"),
    ]
    vault = make_vault(v1_catalog(entries))
    migrate(run_cli)
    assert [entry["id"] for entry in read_catalog(vault)["episodes"]] == ["new", "old"]
