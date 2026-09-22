"""Spec sections: `migrate` Command / Version 1 & 2 to Version 3 Migration /
`sync` on Legacy Vaults / Migration Persistence / Migration Determinism."""
import json
import os
import re

from conftest import (EPOCH, EPOCH_ISO, OLD_EPOCH, OLD_EPOCH_ISO,
                      V1_SOURCE_PREFIX, entry, find, has_backup, make_vault,
                      payload, read_backup, read_bytes, read_catalog,
                      v1_catalog, v1_entry, v2_catalog, v2_entry, v3_catalog,
                      v3_entry)

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
HISTORY_FIELDS = ("title", "description", "views", "likes", "preview")


def all_entries(catalog):
    for category in ("episodes", "streams", "clips"):
        for item in catalog[category]:
            yield item


# --------------------------------------------------------------------------
# `migrate` Command
# --------------------------------------------------------------------------

# Phrase: "Syntax | `python mvault.py migrate <name>`"
def test_migrate_syntax(run, tmp_path):
    make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    result = run("migrate", "v1")
    assert result.returncode == 0, result.stderr


# Phrase: "Syntax | `python mvault.py migrate <name>`"
# Context: the subcommand is discoverable in the usage text.
def test_migrate_listed_in_help(run):
    assert "migrate" in run("--help").stdout


# Phrase: "Input | Existing vault with v1, v2, or v3 catalog"
def test_migrate_accepts_all_three_versions(run, tmp_path):
    make_vault(tmp_path, "a", v1_catalog(entries=[v1_entry("e1")]))
    make_vault(tmp_path, "b", v2_catalog(episodes=[v2_entry("e1")]))
    make_vault(tmp_path, "c", v3_catalog(episodes=[v3_entry("e1")]))
    for name in ("a", "b", "c"):
        result = run("migrate", name)
        assert result.returncode == 0, (name, result.stderr)


# Phrase: "Effect on v1 or v2 | Convert catalog to v3 on disk"
def test_migrate_converts_v1_on_disk(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    assert run("migrate", "v1").returncode == 0
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Phrase: "Effect on v1 or v2 | Convert catalog to v3 on disk" (v2)
def test_migrate_converts_v2_on_disk(run, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(episodes=[v2_entry("e1")]))
    assert run("migrate", "v2").returncode == 0
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Phrase: "Effect on v3 | No-op; no backup written"
# See AMBIGUITIES.md T18.
def test_migrate_on_v3_is_a_no_op_without_backup(run, tmp_path):
    vault = make_vault(tmp_path, "v3", v3_catalog(episodes=[v3_entry("e1")]))
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v3")
    assert result.returncode == 0, result.stderr
    assert read_bytes(vault / "catalog.json") == before
    assert not has_backup(vault)


# Phrase: "Missing vault | Error to stderr including `<name>`; exit non-zero"
def test_migrate_missing_vault_errors_with_name(run):
    result = run("migrate", "nosuch")
    assert result.returncode != 0
    assert "nosuch" in result.stderr
    assert result.stdout == ""


# --------------------------------------------------------------------------
# Version 1 to Version 3 Migration
# --------------------------------------------------------------------------

# Phrase: "`source_id` | Convert to `source` using
#          `https://media.example.com/channel/<source_id>`"
def test_v1_migration_converts_source_id(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(source_id="zz9"))
    assert run("migrate", "v1").returncode == 0
    catalog = read_catalog(vault)
    assert catalog["source"] == "https://media.example.com/channel/zz9"
    assert "source_id" not in catalog


# Phrase: "Entries | Move every object from `entries` to `episodes`"
def test_v1_migration_moves_entries_to_episodes(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(
        entries=[v1_entry("e1"), v1_entry("e2"), v1_entry("e3")]))
    assert run("migrate", "v1").returncode == 0
    catalog = read_catalog(vault)
    assert [e["id"] for e in catalog["episodes"]] == ["e1", "e2", "e3"]
    assert "entries" not in catalog


# Phrase: "Missing categories | Create empty `streams` and `clips` arrays"
def test_v1_migration_creates_empty_categories(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    assert run("migrate", "v1").returncode == 0
    catalog = read_catalog(vault)
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# Phrase: "History keys | Convert every UNIX-epoch string key to ISO 8601
#          format"
def test_v1_migration_converts_every_history_key(run, tmp_path):
    vault = make_vault(tmp_path, "v1",
                       v1_catalog(entries=[v1_entry("e1", epoch=EPOCH)]))
    assert run("migrate", "v1").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    for field in HISTORY_FIELDS:
        assert list(stored[field]) == [EPOCH_ISO], field


# Phrase: "History keys | Convert every UNIX-epoch string key to ISO 8601
#          format"
# Context: an entry whose fields carry several keys each converts all of them.
def test_v1_migration_converts_multiple_keys_per_field(run, tmp_path):
    item = v1_entry("e1")
    item["views"] = {str(OLD_EPOCH): 1, str(EPOCH): 2}
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[item]))
    assert run("migrate", "v1").returncode == 0
    assert read_catalog(vault)["episodes"][0]["views"] == {
        OLD_EPOCH_ISO: 1, EPOCH_ISO: 2}


# Phrase: "`removed` | Add `{<migration-timestamp>: false}` to every entry"
def test_v1_migration_adds_removed_to_every_entry(run, tmp_path):
    vault = make_vault(tmp_path, "v1",
                       v1_catalog(entries=[v1_entry("e1"), v1_entry("e2")]))
    assert run("migrate", "v1").returncode == 0
    for stored in read_catalog(vault)["episodes"]:
        assert list(stored["removed"].values()) == [False]
        assert TS_RE.match(list(stored["removed"])[0])


# Phrase: "`annotations` | Add `[]` to every entry"
def test_v1_migration_adds_empty_annotations(run, tmp_path):
    vault = make_vault(tmp_path, "v1",
                       v1_catalog(entries=[v1_entry("e1"), v1_entry("e2")]))
    assert run("migrate", "v1").returncode == 0
    for stored in read_catalog(vault)["episodes"]:
        assert stored["annotations"] == []


# Phrase: "Version field | Set `version` to `3`"
def test_v1_migration_sets_version_three(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    assert run("migrate", "v1").returncode == 0
    assert read_catalog(vault)["version"] == 3


# --------------------------------------------------------------------------
# Version 2 to Version 3 Migration
# --------------------------------------------------------------------------

# Phrase: "`source` | Preserve existing value"
def test_v2_migration_preserves_source(run, tmp_path):
    vault = make_vault(tmp_path, "v2",
                       v2_catalog(source="http://kept.invalid/f.json"))
    assert run("migrate", "v2").returncode == 0
    assert read_catalog(vault)["source"] == "http://kept.invalid/f.json"


# Phrase: "Categories | Preserve `episodes`, `streams`, and `clips` placement"
def test_v2_migration_preserves_category_placement(run, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(
        episodes=[v2_entry("e1")],
        streams=[v2_entry("s1"), v2_entry("s2")],
        clips=[v2_entry("c1")]))
    assert run("migrate", "v2").returncode == 0
    catalog = read_catalog(vault)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1", "s2"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Phrase: "`removed` | Add `{<migration-timestamp>: false}` to every entry in
#          every category"
def test_v2_migration_adds_removed_in_every_category(run, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(
        episodes=[v2_entry("e1")], streams=[v2_entry("s1")],
        clips=[v2_entry("c1")]))
    assert run("migrate", "v2").returncode == 0
    for stored in all_entries(read_catalog(vault)):
        assert list(stored["removed"].values()) == [False]
        assert TS_RE.match(list(stored["removed"])[0])


# Phrase: "`annotations` | Add `[]` to every entry"
def test_v2_migration_adds_empty_annotations(run, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(
        episodes=[v2_entry("e1")], streams=[v2_entry("s1")],
        clips=[v2_entry("c1")]))
    assert run("migrate", "v2").returncode == 0
    for stored in all_entries(read_catalog(vault)):
        assert stored["annotations"] == []


# Phrase: "Version field | Set `version` to `3`"
def test_v2_migration_sets_version_three(run, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(episodes=[v2_entry("e1")]))
    assert run("migrate", "v2").returncode == 0
    assert read_catalog(vault)["version"] == 3


# Phrase: Version 2 to Version 3 Migration — ISO history keys and values are
# untouched by the conversion.
def test_v2_migration_keeps_history_verbatim(run, tmp_path):
    item = v2_entry("e1", stamp="2020-03-04T05:06:07", title="keep", views=42)
    vault = make_vault(tmp_path, "v2", v2_catalog(episodes=[item]))
    assert run("migrate", "v2").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    assert stored["title"] == {"2020-03-04T05:06:07": "keep"}
    assert stored["views"] == {"2020-03-04T05:06:07": 42}


# --------------------------------------------------------------------------
# `sync` on Legacy Vaults
# --------------------------------------------------------------------------

# Phrase: "v1 vault | Auto-migrate to v3 in memory, apply sync updates, write
#          v3 catalog to disk"
def test_sync_migrates_v1_and_writes_v3(run_inproc, tmp_path):
    vault = make_vault(tmp_path, "v1",
                       v1_catalog(source_id="k", entries=[v1_entry("e1", title="old")]))
    url = V1_SOURCE_PREFIX + "k"
    result = run_inproc("sync", "v1",
                        responses={url: payload(episodes=[entry("e1", title="new")])})
    assert result.returncode == 0, result.stderr
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert catalog["source"] == url
    stored = catalog["episodes"][0]
    assert stored["title"][EPOCH_ISO] == "old"
    assert stored["title"][max(stored["title"])] == "new"


# Phrase: "v2 vault | Auto-migrate to v3 in memory, apply sync updates, write
#          v3 catalog to disk"
def test_sync_migrates_v2_and_writes_v3(run, source, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(
        source=source.url, episodes=[v2_entry("e1", title="old")]))
    source.payload = payload(episodes=[entry("e1", title="new")])
    result = run("sync", "v2")
    assert result.returncode == 0, result.stderr
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    stored = catalog["episodes"][0]
    assert stored["title"][EPOCH_ISO] == "old"
    assert stored["title"][max(stored["title"])] == "new"
    assert stored["annotations"] == []
    assert list(stored["removed"].values()) == [False]


# Phrase: "v3 vault | Normal sync behavior"
def test_sync_on_v3_is_unchanged(run, source, tmp_path):
    vault = make_vault(tmp_path, "v3", v3_catalog(
        source=source.url, episodes=[v3_entry("e1", title="old")]))
    source.payload = payload(episodes=[entry("e1", title="new")])
    assert run("sync", "v3").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    assert stored["title"][max(stored["title"])] == "new"
    assert stored["title"][EPOCH_ISO] == "old"


# Phrase: "Entries created by `sync` | Written in v3 shape, with `annotations`
#          as `[]`"
def test_sync_created_entries_have_v3_shape(run, source, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(source=source.url))
    source.payload = payload(episodes=[entry("new1")])
    assert run("sync", "v2").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    assert stored["annotations"] == []
    assert list(stored["removed"].values()) == [False]
    assert set(stored) == {"id", "published", "width", "height", "title",
                           "description", "views", "likes", "preview",
                           "removed", "annotations"}


# Phrase: "Entries created by `sync` | Written in v3 shape, with `annotations`
#          as `[]`"
# Context: also true for a vault that was created by `init` (already v3).
def test_sync_created_entries_in_native_vault_have_annotations(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("e1")])
    assert run("sync", "v").returncode == 0
    assert read_catalog(tmp_path / "v")["episodes"][0]["annotations"] == []


# Phrase: "Source URL for v1 | Derive from `source_id` using the standard
#          derivation"
def test_sync_v1_uses_derived_source_and_stores_it(run_inproc, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(source_id="ch-7"))
    url = V1_SOURCE_PREFIX + "ch-7"
    result = run_inproc("sync", "v1", responses={url: payload()})
    assert result.returncode == 0, result.stderr
    assert result.calls == [url]
    assert read_catalog(vault)["source"] == url


# Phrase: "Backup before write | Standard backup rules apply; backup contains
#          the **original** pre-migration catalog"
def test_sync_backup_holds_original_v2_catalog(run, source, tmp_path):
    original = v2_catalog(source=source.url, episodes=[v2_entry("e1")])
    vault = make_vault(tmp_path, "v2", original)
    source.payload = payload(episodes=[entry("e1")])
    assert run("sync", "v2").returncode == 0
    assert read_backup(vault) == original
    assert read_catalog(vault)["version"] == 3


# Phrase: "Backup before write | ... backup contains the **original**
#          pre-migration catalog" (v1)
def test_sync_backup_holds_original_v1_catalog(run_inproc, tmp_path):
    original = v1_catalog(source_id="k", entries=[v1_entry("e1")])
    vault = make_vault(tmp_path, "v1", original)
    url = V1_SOURCE_PREFIX + "k"
    result = run_inproc("sync", "v1",
                        responses={url: payload(episodes=[entry("e1")])})
    assert result.returncode == 0, result.stderr
    assert read_backup(vault) == original


# --------------------------------------------------------------------------
# Migration Persistence
# --------------------------------------------------------------------------

# Phrase: "Trigger | `migrate` command or `sync` on a v1/v2 vault"
# Context: both paths leave a v3 catalog on disk.
def test_migration_triggers(run, source, tmp_path):
    vault_a = make_vault(tmp_path, "a", v2_catalog(source=source.url))
    vault_b = make_vault(tmp_path, "b", v2_catalog(source=source.url))
    assert run("migrate", "a").returncode == 0
    assert run("sync", "b").returncode == 0
    assert read_catalog(vault_a)["version"] == 3
    assert read_catalog(vault_b)["version"] == 3


# Phrase: "Backup timing | Copy original `catalog.json` to `catalog.bak` before
#          migration write"
def test_migrate_writes_backup_of_original(run, tmp_path):
    original = v1_catalog(entries=[v1_entry("e1")])
    vault = make_vault(tmp_path, "v1", original)
    assert run("migrate", "v1").returncode == 0
    assert has_backup(vault)
    assert read_backup(vault) == original


# Phrase: "Backup content | Semantically equivalent pre-migration JSON snapshot"
def test_backup_is_semantically_equivalent_to_pre_migration_catalog(run, tmp_path):
    original = v2_catalog(episodes=[v2_entry("e1")], streams=[v2_entry("s1")])
    vault = make_vault(tmp_path, "v2", original)
    assert run("migrate", "v2").returncode == 0
    assert read_backup(vault) == original


# Phrase: "Save timing | Save migrated v3 catalog immediately"
def test_migrate_saves_immediately(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    assert run("migrate", "v1").returncode == 0
    assert read_catalog(vault)["version"] == 3


# Phrase: "Post-migration usability | All subsequent commands operate as for a
#          vault created in v3"
def test_commands_work_normally_after_migration(run, source, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(
        source=source.url, episodes=[v2_entry("e1", title="old")]))
    assert run("migrate", "v2").returncode == 0
    source.payload = payload(episodes=[entry("e1", title="new")])
    assert run("sync", "v2").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    assert stored["title"][max(stored["title"])] == "new"
    assert len(stored["title"]) == 2
    source.payload = payload()
    assert run("sync", "v2").returncode == 0
    stored = read_catalog(vault)["episodes"][0]
    assert stored["removed"][max(stored["removed"])] is True


# --------------------------------------------------------------------------
# Migration Determinism
# --------------------------------------------------------------------------

# Phrase: "Migration-added `removed` value | Single history entry with value
#          `false`"
def test_migration_removed_is_single_false_entry(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    assert run("migrate", "v1").returncode == 0
    removed = read_catalog(vault)["episodes"][0]["removed"]
    assert len(removed) == 1
    assert list(removed.values()) == [False]


# Phrase: "Migration-added timestamp scope | Each migration-added `removed`
#          timestamp must be ISO 8601; cross-entry equality is not required"
def test_migration_timestamps_are_iso_8601(run, tmp_path):
    vault = make_vault(tmp_path, "v2", v2_catalog(
        episodes=[v2_entry("e1")], streams=[v2_entry("s1")],
        clips=[v2_entry("c1")]))
    assert run("migrate", "v2").returncode == 0
    for stored in all_entries(read_catalog(vault)):
        key = list(stored["removed"])[0]
        assert TS_RE.match(key), key


# Phrase: "v1 UNIX-epoch conversion | Convert each epoch-seconds key to
#          `YYYY-MM-DDTHH:MM:SS` in UTC"
def test_epoch_conversion_is_utc(run, tmp_path):
    item = v1_entry("e1")
    item["title"] = {"0": "zero", "1700000000": "later"}
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[item]))
    assert run("migrate", "v1").returncode == 0
    assert read_catalog(vault)["episodes"][0]["title"] == {
        "1970-01-01T00:00:00": "zero",
        "2023-11-14T22:13:20": "later",
    }


# Phrase: "v1 category target | Every migrated entry goes to `episodes`"
def test_every_v1_entry_goes_to_episodes(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(
        entries=[v1_entry("e%d" % i) for i in range(5)]))
    assert run("migrate", "v1").returncode == 0
    catalog = read_catalog(vault)
    assert len(catalog["episodes"]) == 5
    assert catalog["streams"] == [] and catalog["clips"] == []


# Phrase: "v1 `source_id` conversion |
#          `https://media.example.com/channel/<source_id>`"
def test_source_id_conversion_is_exact(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(source_id="a_b-c.9"))
    assert run("migrate", "v1").returncode == 0
    assert read_catalog(vault)["source"] == \
        "https://media.example.com/channel/a_b-c.9"


# Phrase: "v3 reload | No additional history entry, no semantic modification,
#          no backup write"
def test_v3_reload_adds_nothing(run, tmp_path):
    vault = make_vault(tmp_path, "v3", v3_catalog(episodes=[v3_entry("e1")]))
    before = read_bytes(vault / "catalog.json")
    assert run("migrate", "v3").returncode == 0
    assert read_bytes(vault / "catalog.json") == before
    assert not has_backup(vault)


# Phrase: "Idempotence | Re-loading already migrated v3 catalog produces no
#          further effects"
def test_migration_is_idempotent(run, tmp_path):
    vault = make_vault(tmp_path, "v1", v1_catalog(entries=[v1_entry("e1")]))
    assert run("migrate", "v1").returncode == 0
    migrated = read_bytes(vault / "catalog.json")
    backup = read_bytes(vault / "catalog.bak")
    assert run("migrate", "v1").returncode == 0
    assert read_bytes(vault / "catalog.json") == migrated
    assert read_bytes(vault / "catalog.bak") == backup
