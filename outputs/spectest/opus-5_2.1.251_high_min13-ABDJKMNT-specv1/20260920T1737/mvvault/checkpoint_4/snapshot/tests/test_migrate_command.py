"""Spec section: `migrate` Command."""

import json

from conftest import EPOCH_KEY, ISO_KEY, legacy_entry, read_catalog, v1_catalog, v2_catalog, write_vault


def migrate(run_cli, name="legacy"):
    return run_cli("migrate", name)


# Phrase: "Syntax | `python mvault.py migrate <name>`"
def test_migrate_is_an_available_subcommand(run_cli):
    assert "migrate" in run_cli("--help").stdout


# Phrase: "Input | Existing vault with v1, v2, or v3 catalog" - v1 input succeeds
def test_migrate_accepts_a_v1_vault(run_cli, tmp_path):
    write_vault(tmp_path, "legacy", v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    result = migrate(run_cli)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


# Phrase: "Effect on v1 or v2 | Convert catalog to v3 on disk" - v1
def test_migrate_converts_v1_catalog_on_disk(run_cli, tmp_path):
    vault = write_vault(tmp_path, "legacy", v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    migrate(run_cli)
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert "source_id" not in catalog
    assert "entries" not in catalog


# Phrase: "Effect on v1 or v2 | Convert catalog to v3 on disk" - v2
def test_migrate_converts_v2_catalog_on_disk(run_cli, tmp_path):
    vault = write_vault(
        tmp_path, "legacy", v2_catalog("http://example.test/feed.json", episodes=[legacy_entry("e1", ISO_KEY)])
    )
    migrate(run_cli)
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert catalog["source"] == "http://example.test/feed.json"


# Phrase: "Effect on v3 | No-op; no backup written"
def test_migrate_on_v3_writes_no_backup(run_cli, source, vault):
    migrate(run_cli, "demo")
    assert not (vault / "catalog.bak").exists()


# Phrase: "Effect on v3 | No-op" - the catalog file itself is untouched
def test_migrate_on_v3_leaves_the_catalog_untouched(run_cli, source, vault):
    before = (vault / "catalog.json").read_bytes()
    result = migrate(run_cli, "demo")
    assert result.returncode == 0, result.stderr
    assert (vault / "catalog.json").read_bytes() == before


# Phrase: "Missing vault | Error to stderr including `<name>`; exit non-zero"
def test_migrate_missing_vault_errors_with_the_name(run_cli):
    result = migrate(run_cli, "nope")
    assert result.returncode != 0
    assert "nope" in result.stderr
    assert result.stdout == ""


# Phrase: "Missing vault" - a directory without `catalog.json` is also missing
def test_migrate_vault_without_catalog_errors(run_cli, tmp_path):
    (tmp_path / "empty").mkdir()
    result = migrate(run_cli, "empty")
    assert result.returncode != 0
    assert "empty" in result.stderr


# Phrase: "Backup timing | Copy original `catalog.json` to `catalog.bak` before migration write"
def test_migrate_backs_up_the_original_catalog(run_cli, tmp_path):
    original = v1_catalog(legacy_entry("e1", EPOCH_KEY))
    vault = write_vault(tmp_path, "legacy", original)
    migrate(run_cli)
    assert json.loads((vault / "catalog.bak").read_text()) == original


# Phrase: "Backup content | Semantically equivalent pre-migration JSON snapshot" - v2
def test_migrate_backup_of_v2_is_the_pre_migration_catalog(run_cli, tmp_path):
    original = v2_catalog("http://example.test/feed.json", clips=[legacy_entry("c1", ISO_KEY)])
    vault = write_vault(tmp_path, "legacy", original)
    migrate(run_cli)
    assert json.loads((vault / "catalog.bak").read_text()) == original


# Phrase: "Post-migration usability | All subsequent commands operate as for a vault created in v3"
def test_migrated_vault_syncs_like_a_native_vault(run_cli, source, tmp_path):
    from conftest import current, find_entry, source_entry

    write_vault(tmp_path, "legacy", v2_catalog(source.url, episodes=[legacy_entry("e1", ISO_KEY)]))
    assert migrate(run_cli).returncode == 0
    source.serve(episodes=[source_entry("e1", title="fresh")])
    assert run_cli("sync", "legacy").returncode == 0

    entry = find_entry(read_catalog(tmp_path / "legacy"), "episodes", "e1")
    assert current(entry["title"]) == "fresh"


# Phrase: "Idempotence | Re-loading already migrated v3 catalog produces no further effects"
def test_migrating_twice_changes_nothing_the_second_time(run_cli, tmp_path):
    vault = write_vault(tmp_path, "legacy", v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    migrate(run_cli)
    after_first = (vault / "catalog.json").read_bytes()
    backup_after_first = (vault / "catalog.bak").read_bytes()

    migrate(run_cli)
    assert (vault / "catalog.json").read_bytes() == after_first
    assert (vault / "catalog.bak").read_bytes() == backup_after_first
