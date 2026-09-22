"""Spec sections: `migrate` Command / Version 1 to 3 / Version 2 to 3 migration."""

from __future__ import annotations

import json
import re
from pathlib import Path

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
CATEGORIES = ("episodes", "streams", "clips")


def catalog_path(workdir, name="vault"):
    return Path(workdir) / name / "catalog.json"


def backup_path(workdir, name="vault"):
    return Path(workdir) / name / "catalog.bak"


# Spec: | Syntax | `python mvault.py migrate <name>` |
def test_migrate_syntax_accepted(run_cli, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    result = run_cli("migrate", "vault")
    assert result.returncode == 0, result.stderr


# Spec: | Syntax | `python mvault.py migrate <name>` |
# Context: the subcommand is part of the public CLI surface.
def test_migrate_listed_in_help(run_cli):
    result = run_cli("--help")
    assert result.returncode == 0
    assert "migrate" in result.stdout


# Spec: | Input | Existing vault with v1, v2, or v3 catalog |
#       | Effect on v1 or v2 | Convert catalog to v3 on disk |
def test_migrate_v1_writes_v3_on_disk(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert catalog["version"] == 3


# Spec: | Effect on v1 or v2 | Convert catalog to v3 on disk |
def test_migrate_v2_writes_v3_on_disk(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    assert helpers.read_catalog(workdir)["version"] == 3


# Spec: | Effect on v3 | No-op; no backup written |
def test_migrate_v3_leaves_catalog_unchanged(run_cli, vault, workdir):
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli("migrate", "vault")
    assert result.returncode == 0, result.stderr
    assert catalog_path(workdir).read_text(encoding="utf-8") == before


# Spec: | Effect on v3 | No-op; **no backup written** |
def test_migrate_v3_writes_no_backup(run_cli, vault, workdir):
    assert run_cli("migrate", "vault").returncode == 0
    assert not backup_path(workdir).exists()


# Spec: | Effect on v3 | No-op; no backup written |
# Context: an already-present backup from an earlier migration is not refreshed.
def test_migrate_v3_does_not_refresh_existing_backup(run_cli, make_vault, legacy, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    backup = backup_path(workdir).read_text(encoding="utf-8")
    assert json.loads(backup)["version"] == 1
    assert run_cli("migrate", "vault").returncode == 0
    assert backup_path(workdir).read_text(encoding="utf-8") == backup


# Spec: | Missing vault | Error to stderr including `<name>`; exit non-zero |
def test_migrate_missing_vault_exits_non_zero(run_cli):
    result = run_cli("migrate", "nope")
    assert result.returncode != 0


# Spec: | Missing vault | Error to stderr **including `<name>`** |
def test_migrate_missing_vault_names_the_vault_on_stderr(run_cli):
    result = run_cli("migrate", "nope")
    assert "nope" in result.stderr
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# Version 1 to Version 3 Migration
# ---------------------------------------------------------------------------

# Spec: | `source_id` | Convert to `source` using
#       `https://media.example.com/channel/<source_id>` |
def test_v1_migration_converts_source_id(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(source_id="zeta"))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert catalog["source"] == "https://media.example.com/channel/zeta"
    assert "source_id" not in catalog


# Spec: | Entries | Move every object from `entries` to `episodes` |
def test_v1_migration_moves_entries_to_episodes(run_cli, make_vault, legacy, helpers, workdir):
    entries = [legacy.v1_entry("e1"), legacy.v1_entry("e2"), legacy.v1_entry("e3")]
    make_vault(legacy.v1_catalog(entries=entries))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert sorted(e["id"] for e in catalog["episodes"]) == ["e1", "e2", "e3"]
    assert "entries" not in catalog


# Spec: | Missing categories | Create empty `streams` and `clips` arrays |
def test_v1_migration_creates_empty_streams_and_clips(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# Spec: | History keys | Convert every UNIX-epoch string key to ISO 8601 format |
def test_v1_migration_converts_every_history_key(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in ("title", "description", "views", "likes", "preview"):
        assert list(entry[field]) == [legacy.V1_EPOCH_ISO], field


# Spec: | History keys | Convert every UNIX-epoch string key to ISO 8601 format |
# Context: multi-key histories keep every value, re-keyed.
def test_v1_migration_converts_multi_key_history(run_cli, make_vault, legacy, helpers, workdir):
    entry = legacy.v1_entry("e1", views={
        legacy.V1_EPOCH: 10, legacy.V1_EPOCH_LATER: 20})
    make_vault(legacy.v1_catalog(entries=[entry]))
    assert run_cli("migrate", "vault").returncode == 0
    stored = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert stored["views"] == {
        legacy.V1_EPOCH_ISO: 10, legacy.V1_EPOCH_LATER_ISO: 20}


# Spec: | `removed` | Add `{<migration-timestamp>: false}` to every entry |
def test_v1_migration_adds_removed_to_every_entry(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1"), legacy.v1_entry("e2")]))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    for entry in catalog["episodes"]:
        assert list(entry["removed"].values()) == [False]
        assert ISO_RE.match(next(iter(entry["removed"])))


# Spec: | `annotations` | Add `[]` to every entry |
def test_v1_migration_adds_empty_annotations(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1"), legacy.v1_entry("e2")]))
    assert run_cli("migrate", "vault").returncode == 0
    for entry in helpers.read_catalog(workdir)["episodes"]:
        assert entry["annotations"] == []


# Spec: | Version field | Set `version` to `3` |
def test_v1_migration_sets_version_three(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    version = helpers.read_catalog(workdir)["version"]
    assert version == 3 and isinstance(version, int)


# ---------------------------------------------------------------------------
# Version 2 to Version 3 Migration
# ---------------------------------------------------------------------------

# Spec: | `source` | Preserve existing value |
def test_v2_migration_preserves_source(run_cli, make_vault, legacy, helpers, workdir, source):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    assert helpers.read_catalog(workdir)["source"] == source.url


# Spec: | Categories | Preserve `episodes`, `streams`, and `clips` placement |
def test_v2_migration_preserves_category_placement(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v2_catalog(
        episodes=[legacy.v2_entry("e1")],
        streams=[legacy.v2_entry("s1")],
        clips=[legacy.v2_entry("c1")],
    ))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Spec: | `removed` | Add `{<migration-timestamp>: false}` to every entry in
#       every category |
def test_v2_migration_adds_removed_in_every_category(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v2_catalog(
        episodes=[legacy.v2_entry("e1")],
        streams=[legacy.v2_entry("s1")],
        clips=[legacy.v2_entry("c1")],
    ))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    for category in CATEGORIES:
        for entry in catalog[category]:
            assert list(entry["removed"].values()) == [False], category
            assert ISO_RE.match(next(iter(entry["removed"])))


# Spec: | `annotations` | Add `[]` to every entry |
def test_v2_migration_adds_empty_annotations(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v2_catalog(
        episodes=[legacy.v2_entry("e1")], streams=[legacy.v2_entry("s1")]))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    for category in CATEGORIES:
        for entry in catalog[category]:
            assert entry["annotations"] == []


# Spec: | Version field | Set `version` to `3` |
def test_v2_migration_sets_version_three(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    assert helpers.read_catalog(workdir)["version"] == 3


# Spec: Version 2 to 3: the entry payload itself is otherwise preserved
# (only `removed`, `annotations` and `version` are added).
def test_v2_migration_preserves_entry_history(run_cli, make_vault, legacy, helpers, workdir):
    entry = legacy.v2_entry("e1", title={"2024-02-03T04:05:06": "Kept"}, likes={"2024-02-03T04:05:06": None})
    make_vault(legacy.v2_catalog(episodes=[entry]))
    assert run_cli("migrate", "vault").returncode == 0
    stored = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert stored["title"] == {"2024-02-03T04:05:06": "Kept"}
    assert stored["likes"] == {"2024-02-03T04:05:06": None}
    assert stored["published"] == "2024-05-01T08:30:00"
    assert stored["width"] == 1920 and stored["height"] == 1080


# ---------------------------------------------------------------------------
# Migration Persistence
# ---------------------------------------------------------------------------

# Spec: | Trigger | `migrate` command or `sync` on a v1/v2 vault |
#       | Backup timing | Copy original `catalog.json` to `catalog.bak` before
#       migration write |
def test_migrate_writes_backup(run_cli, make_vault, legacy, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    assert backup_path(workdir).is_file()


# Spec: | Backup content | Semantically equivalent pre-migration JSON snapshot |
def test_migrate_backup_holds_pre_migration_catalog(run_cli, make_vault, legacy, workdir):
    original = legacy.v1_catalog(source_id="abc", entries=[legacy.v1_entry("e1")])
    make_vault(original)
    assert run_cli("migrate", "vault").returncode == 0
    assert json.loads(backup_path(workdir).read_text(encoding="utf-8")) == original


# Spec: | Backup content | Semantically equivalent pre-migration JSON snapshot |
# Context: same rule for a v2 catalog.
def test_migrate_v2_backup_holds_pre_migration_catalog(run_cli, make_vault, legacy, workdir):
    original = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")])
    make_vault(original)
    assert run_cli("migrate", "vault").returncode == 0
    assert json.loads(backup_path(workdir).read_text(encoding="utf-8")) == original


# Spec: | Save timing | Save migrated v3 catalog immediately |
def test_migrate_saves_v3_immediately(run_cli, make_vault, legacy, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    on_disk = json.loads(catalog_path(workdir).read_text(encoding="utf-8"))
    assert on_disk["version"] == 3
    assert on_disk["episodes"][0]["annotations"] == []


# Spec: | Post-migration usability | All subsequent commands operate as for a
#       vault created in v3 |
def test_post_migration_sync_behaves_natively(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("e1", views=555),
        helpers.make_source_entry("e2"),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert helpers.current(helpers.find_entry(catalog, "e1")["views"]) == 555
    assert helpers.find_entry(catalog, "e2") is not None
    assert catalog["version"] == 3
