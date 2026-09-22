"""Spec sections: `migrate` Command, Migration Persistence."""

import json

from conftest import (
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


# Spec: Syntax | `python mvault.py migrate <name>`
def test_migrate_takes_a_vault_name(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    assert run("migrate", "vault").returncode == 0
    assert run("migrate").returncode != 0


# Spec: Effect on v1 or v2 | Convert catalog to v3 on disk
def test_migrate_converts_v1_on_disk(run, tmp_path):
    directory = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    run("migrate", "vault")
    assert read_catalog(directory)["version"] == 3


# Spec: Effect on v1 or v2 | Convert catalog to v3 on disk
def test_migrate_converts_v2_on_disk(run, tmp_path):
    directory = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")]))
    run("migrate", "vault")
    assert read_catalog(directory)["version"] == 3


# Spec: Effect on v3 | No-op; no backup written
def test_migrate_on_v3_writes_no_backup(run, vault):
    before = (vault / "catalog.json").read_bytes()
    result = run("migrate", "vault")

    assert result.returncode == 0
    assert (vault / "catalog.json").read_bytes() == before
    assert not (vault / "catalog.bak").exists()


# Spec: Missing vault | Error to stderr including `<name>`; exit non-zero
def test_migrate_missing_vault_names_the_vault(run):
    result = run("migrate", "nowhere")
    assert result.returncode != 0
    assert "nowhere" in result.stderr
    assert result.stdout == ""


# Spec: Missing vault | Error ... (a directory without a catalog is equally unusable)
def test_migrate_directory_without_catalog_errors(run, tmp_path):
    (tmp_path / "vault").mkdir()
    result = run("migrate", "vault")
    assert result.returncode != 0
    assert "vault" in result.stderr
    assert "Traceback" not in result.stderr


# Spec: Backup timing | Copy original `catalog.json` to `catalog.bak` before migration write
def test_migration_writes_a_backup(run, tmp_path):
    directory = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    run("migrate", "vault")
    assert (directory / "catalog.bak").is_file()


# Spec: Backup content | Semantically equivalent pre-migration JSON snapshot
def test_backup_holds_the_pre_migration_catalog(run, tmp_path):
    original = v1_catalog(entries=[v1_entry("e1")])
    directory = write_vault(tmp_path, original)
    run("migrate", "vault")

    assert read_backup(directory) == original


# Spec: Backup content | Semantically equivalent pre-migration JSON snapshot (v2)
def test_v2_backup_holds_the_pre_migration_catalog(run, tmp_path):
    original = v2_catalog(episodes=[v2_entry("e1")], streams=[v2_entry("s1")])
    directory = write_vault(tmp_path, original)
    run("migrate", "vault")

    assert read_backup(directory) == original


# Spec: Save timing | Save migrated v3 catalog immediately
def test_migrated_catalog_is_saved_as_valid_json(run, tmp_path):
    directory = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    run("migrate", "vault")

    catalog = json.loads((directory / "catalog.json").read_text())
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Spec: Post-migration usability | All subsequent commands operate as for a vault created in v3
def test_sync_after_migrate_behaves_like_a_native_vault(run, tmp_path, source):
    directory = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=source.url))
    assert run("migrate", "vault").returncode == 0

    source.serve(payload(episodes=[source_entry("e1", title="fresh")]))
    assert run("sync", "vault").returncode == 0

    title = read_catalog(directory)["episodes"][0]["title"]
    assert title[max(title)] == "fresh"


# Spec: Post-migration usability | ... (a second migrate finds nothing left to do)
def test_migrate_twice_is_a_no_op_the_second_time(run, tmp_path):
    directory = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    run("migrate", "vault")
    after_first = (directory / "catalog.json").read_bytes()
    backup_after_first = (directory / "catalog.bak").read_bytes()

    assert run("migrate", "vault").returncode == 0
    assert (directory / "catalog.json").read_bytes() == after_first
    assert (directory / "catalog.bak").read_bytes() == backup_after_first


# Spec: `migrate` ... (success is silent)
def test_successful_migrate_is_silent(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    result = run("migrate", "vault")
    assert (result.stdout, result.stderr) == ("", "")
