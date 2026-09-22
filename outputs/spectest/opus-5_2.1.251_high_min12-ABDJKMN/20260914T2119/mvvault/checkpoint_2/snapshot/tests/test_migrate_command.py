"""Spec: the `migrate` command and Migration Persistence."""
import json
import os

from conftest import (EPOCH_A, ISO_A, backup_path, catalog_bytes, catalog_path,
                      find_entry, make_entry, make_v1_catalog, make_v1_entry,
                      make_v2_catalog, make_v2_entry, make_v3_catalog,
                      make_v3_entry, read_catalog, read_json)


# Spec: "| Syntax | `python mvault.py migrate <name>` |"
def test_migrate_syntax_accepted(run, make_vault):
    make_vault(make_v1_catalog())
    res = run("migrate", "vault")
    assert res.returncode == 0, res


# Spec: "Syntax | `python mvault.py migrate <name>`" -- the subcommand is part
# of the published CLI surface.
def test_migrate_listed_in_help(run):
    assert "migrate" in run("--help").stdout


# Spec: "| Input | Existing vault with v1, v2, or v3 catalog |" -- v1.
def test_migrate_accepts_v1_input(run, make_vault):
    make_vault(make_v1_catalog())
    assert run("migrate", "vault").returncode == 0


# Spec: "Input | Existing vault with v1, v2, or v3 catalog" -- v2.
def test_migrate_accepts_v2_input(run, make_vault):
    make_vault(make_v2_catalog())
    assert run("migrate", "vault").returncode == 0


# Spec: "Input | Existing vault with v1, v2, or v3 catalog" -- v3.
def test_migrate_accepts_v3_input(run, make_vault):
    make_vault(make_v3_catalog(episodes=[make_v3_entry()]))
    assert run("migrate", "vault").returncode == 0


# Spec: "| Effect on v1 or v2 | Convert catalog to v3 on disk |" -- v1.
def test_migrate_converts_v1_on_disk(run, tmp_path, make_vault):
    make_vault(make_v1_catalog())
    run("migrate", "vault")
    assert read_catalog(tmp_path)["version"] == 3


# Spec: "Effect on v1 or v2 | Convert catalog to v3 on disk" -- v2.
def test_migrate_converts_v2_on_disk(run, tmp_path, make_vault):
    make_vault(make_v2_catalog())
    run("migrate", "vault")
    assert read_catalog(tmp_path)["version"] == 3


# Spec: "| Effect on v3 | No-op; no backup written |" -- the catalog file is
# left exactly as it was.
def test_migrate_on_v3_is_a_no_op(run, tmp_path, make_vault):
    make_vault(make_v3_catalog(episodes=[make_v3_entry()]))
    before = catalog_bytes(tmp_path)
    assert run("migrate", "vault").returncode == 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Effect on v3 | No-op; **no backup written**"
def test_migrate_on_v3_writes_no_backup(run, tmp_path, make_vault):
    make_vault(make_v3_catalog(episodes=[make_v3_entry()]))
    run("migrate", "vault")
    assert not os.path.exists(backup_path(tmp_path))


# Spec: "| Missing vault | Error to stderr including `<name>`; exit non-zero |"
def test_migrate_missing_vault_exit_non_zero(run):
    assert run("migrate", "nosuchvault").returncode != 0


# Spec: "Missing vault | Error to stderr **including `<name>`**; exit non-zero"
def test_migrate_missing_vault_names_the_vault_on_stderr(run):
    res = run("migrate", "nosuchvault")
    assert "nosuchvault" in res.stderr


# Spec: "Missing vault | Error to **stderr** ..." -- nothing is created.
def test_migrate_missing_vault_creates_nothing(run, tmp_path):
    run("migrate", "nosuchvault")
    assert not (tmp_path / "nosuchvault").exists()


# Spec: "| Trigger | `migrate` command or `sync` on a v1/v2 vault |" +
# "| Backup timing | Copy original `catalog.json` to `catalog.bak` before
# migration write |"
def test_migrate_writes_backup(run, tmp_path, make_vault):
    make_vault(make_v1_catalog())
    run("migrate", "vault")
    assert os.path.isfile(backup_path(tmp_path))


# Spec: "| Backup content | Semantically equivalent pre-migration JSON snapshot |"
def test_backup_holds_the_pre_migration_catalog(run, tmp_path, make_vault):
    original = make_v1_catalog(entries=[make_v1_entry(id="e1")])
    make_vault(original)
    run("migrate", "vault")
    assert read_json(backup_path(tmp_path)) == original


# Spec: "Backup content | Semantically equivalent pre-migration JSON snapshot"
# -- version 2 vaults too.
def test_backup_holds_the_pre_migration_v2_catalog(run, tmp_path, make_vault):
    original = make_v2_catalog(episodes=[make_v2_entry(id="e1")],
                               streams=[make_v2_entry(id="s1")])
    make_vault(original)
    run("migrate", "vault")
    assert read_json(backup_path(tmp_path)) == original


# Spec: "| Save timing | Save migrated v3 catalog immediately |"
# Context: the converted catalog is on disk when the command returns.
def test_migrated_catalog_saved_immediately(run, tmp_path, make_vault):
    make_vault(make_v1_catalog())
    run("migrate", "vault")
    saved = read_json(catalog_path(tmp_path))
    assert saved["version"] == 3
    assert list(saved["episodes"][0]["removed"].values()) == [False]


# Spec: "| Post-migration usability | All subsequent commands operate as for a
# vault created in v3 |" -- a migrated v2 vault syncs like a native one.
def test_migrated_vault_syncs_like_a_native_vault(run, source, tmp_path,
                                                  make_vault):
    make_vault(make_v2_catalog(source=source.url,
                               episodes=[make_v2_entry(id="e1")]))
    assert run("migrate", "vault").returncode == 0
    source.serve(episodes=[make_entry(id="e1", title="Fresh"),
                           make_entry(id="e2")])
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert catalog["version"] == 3
    assert {e["id"] for e in catalog["episodes"]} == {"e1", "e2"}


# Spec: "Post-migration usability | All subsequent commands operate as for a
# vault created in v3" -- a second `migrate` is the v3 no-op.
def test_migrate_twice_is_a_no_op_the_second_time(run, tmp_path, make_vault):
    make_vault(make_v1_catalog())
    run("migrate", "vault")
    after_first = catalog_bytes(tmp_path)
    backup_after_first = open(backup_path(tmp_path), "rb").read()

    assert run("migrate", "vault").returncode == 0
    assert catalog_bytes(tmp_path) == after_first
    assert open(backup_path(tmp_path), "rb").read() == backup_after_first
