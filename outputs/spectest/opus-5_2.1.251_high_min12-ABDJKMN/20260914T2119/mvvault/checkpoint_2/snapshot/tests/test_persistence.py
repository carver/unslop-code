"""Spec: `catalog.json` Persistence."""
import json
import os

from conftest import backup_path, catalog_path, make_entry, read_catalog


# Spec: "| Backup trigger | Before every write to existing `catalog.json` |" +
# "| Backup path | `catalog.bak` |" (see AMBIGUITIES T1).
def test_backup_created_beside_catalog_on_sync(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    assert run("sync", "vault").returncode == 0
    assert os.path.isfile(backup_path(tmp_path))


# Spec: "| Backup content | Byte-for-byte copy of pre-write `catalog.json` |"
def test_backup_is_byte_for_byte_pre_write_catalog(run, source, tmp_path, vault):
    with open(catalog_path(tmp_path), "rb") as fh:
        before = fh.read()

    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")

    with open(backup_path(tmp_path), "rb") as fh:
        assert fh.read() == before


# Spec: "Backup content | Byte-for-byte copy of pre-write `catalog.json`" --
# still exact after several syncs (the backup mirrors the previous generation).
def test_backup_tracks_previous_generation(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="A")])
    run("sync", "vault")
    with open(catalog_path(tmp_path), "rb") as fh:
        gen1 = fh.read()

    source.serve(episodes=[make_entry(id="e1", title="B")])
    run("sync", "vault")

    with open(backup_path(tmp_path), "rb") as fh:
        assert fh.read() == gen1
    assert json.loads(gen1)["episodes"][0]["title"] != \
        read_catalog(tmp_path)["episodes"][0]["title"]


# Spec: "| Backup overwrite | Replace existing `catalog.bak` |"
def test_backup_overwrites_existing_file(run, source, tmp_path, vault):
    stale = backup_path(tmp_path)
    with open(stale, "w", encoding="utf-8") as fh:
        fh.write("stale contents that must be replaced")

    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")

    with open(stale, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "stale" not in content
    assert json.loads(content)["version"] == 3


# Spec: "Backup trigger | Before every write ..." -- every successful sync
# refreshes the backup, including one that detects no changes
# (see AMBIGUITIES T8).
def test_no_op_sync_still_backs_up(run, source, tmp_path, vault):
    payload = [make_entry(id="e1")]
    source.serve(episodes=payload)
    run("sync", "vault")
    os.remove(backup_path(tmp_path))

    source.serve(episodes=payload)
    assert run("sync", "vault").returncode == 0
    assert os.path.isfile(backup_path(tmp_path))
    with open(backup_path(tmp_path), "rb") as fh:
        assert json.loads(fh.read())["episodes"][0]["id"] == "e1"


# Spec: "Backup trigger | Before every write to *existing* `catalog.json`" --
# `init` writes a brand new catalog, so no backup is produced.
def test_init_produces_no_backup(run, tmp_path):
    run("init", "fresh", "http://example.invalid/s.json")
    assert not os.path.exists(backup_path(tmp_path, "fresh"))


# Spec: the backup is a copy, not a move -- catalog.json remains valid and
# up to date after the write.
def test_catalog_remains_valid_after_backup(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert catalog["version"] == 3
    assert catalog["source"] == source.url
    assert len(catalog["episodes"]) == 1


# Spec: "Backup ... pre-write `catalog.json`" -- the vault directory holds only
# the catalog and its backup.
def test_vault_directory_contents(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    assert sorted(os.listdir(str(tmp_path / "vault"))) == \
        ["catalog.bak", "catalog.json"]
