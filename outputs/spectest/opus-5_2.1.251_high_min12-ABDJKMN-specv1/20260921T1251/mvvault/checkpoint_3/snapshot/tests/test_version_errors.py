"""Spec section: Version Handling Errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def catalog_path(workdir, name="vault"):
    return Path(workdir) / name / "catalog.json"


def backup_path(workdir, name="vault"):
    return Path(workdir) / name / "catalog.bak"


COMMANDS = ("migrate", "sync")


# Spec: | Missing `version` field | Error to stderr; exit non-zero; no migration;
#       no modification |
@pytest.mark.parametrize("command", COMMANDS)
def test_missing_version_errors(run_cli, make_vault, legacy, workdir, command):
    catalog = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")])
    del catalog["version"]
    make_vault(catalog)
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli(command, "vault")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert catalog_path(workdir).read_text(encoding="utf-8") == before
    assert not backup_path(workdir).exists()


# Spec: | Non-integer `version` field | **Version-related error** to stderr; exit
#       non-zero; no migration; no modification |
@pytest.mark.parametrize("value", ["3", 3.5, None, True, [3], {"n": 3}])
def test_non_integer_version_errors(run_cli, make_vault, legacy, workdir, value):
    catalog = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")], version=value)
    make_vault(catalog)
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert catalog_path(workdir).read_text(encoding="utf-8") == before
    assert not backup_path(workdir).exists()


# Spec: | `version` greater than `3` | Version-related error to stderr; exit
#       non-zero; no migration; no modification |
@pytest.mark.parametrize("value", [4, 5, 99])
@pytest.mark.parametrize("command", COMMANDS)
def test_version_greater_than_three_errors(run_cli, make_vault, legacy, workdir, value, command):
    catalog = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")], version=value)
    make_vault(catalog)
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli(command, "vault")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert catalog_path(workdir).read_text(encoding="utf-8") == before
    assert not backup_path(workdir).exists()


# Spec: | `version` greater than `3` | ... |
# Context: versions below `1` name no supported schema either. See AMBIGUITIES.md T18.
@pytest.mark.parametrize("value", [0, -1])
def test_version_below_one_errors(run_cli, make_vault, legacy, workdir, value):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")], version=value))
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()


# Spec: | Invalid JSON in `catalog.json` | Error to stderr; exit non-zero; no migration |
@pytest.mark.parametrize("command", COMMANDS)
def test_invalid_json_errors(run_cli, make_vault, workdir, command):
    make_vault(None, raw="{not json at all,")
    result = run_cli(command, "vault")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert catalog_path(workdir).read_text(encoding="utf-8") == "{not json at all,"
    assert not backup_path(workdir).exists()


# Spec: | Failure writing `catalog.bak` | Error to stderr; exit non-zero; abort
#       migration; leave original `catalog.json` intact |
# Context: the backup path is occupied by a directory, so the copy cannot succeed.
def test_backup_write_failure_aborts_migration(run_cli, make_vault, legacy, workdir):
    vault_dir = make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    (vault_dir / "catalog.bak").mkdir()
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert catalog_path(workdir).read_text(encoding="utf-8") == before
    assert json.loads(before)["version"] == 1


# Spec: | Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave
#       `catalog.json` unchanged |
@pytest.mark.parametrize("entry", [
    "not an object",
    123,
    None,
    {"id": 7},                                        # non-string id
    {"id": "e1"},                                     # no history objects at all
])
def test_malformed_v1_entry_errors(run_cli, make_vault, legacy, workdir, entry):
    make_vault(legacy.v1_catalog(entries=[entry]))
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert catalog_path(workdir).read_text(encoding="utf-8") == before


# Spec: | Malformed v1 or v2 entry data | ... |
# Context: a v1 history key that is not UNIX-epoch seconds cannot be converted.
@pytest.mark.parametrize("key", ["not-a-number", "2024-06-15T09:40:00", ""])
def test_malformed_v1_epoch_key_errors(run_cli, make_vault, legacy, workdir, key):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1", title={key: "T"})]))
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert catalog_path(workdir).read_text(encoding="utf-8") == before


# Spec: | Malformed v1 or v2 entry data | ... |
# Context: a history field that is not an object at all. See AMBIGUITIES.md T16.
@pytest.mark.parametrize("field,value", [
    ("title", "plain string"),
    ("views", [1, 2]),
    ("likes", 10),
    ("views", {"1718444400": "many"}),   # wrong history value type
    ("title", {"1718444400": 5}),
])
def test_malformed_v1_history_errors(run_cli, make_vault, legacy, workdir, field, value):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1", **{field: value})]))
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert catalog_path(workdir).read_text(encoding="utf-8") == before


# Spec: | Malformed v1 or v2 entry data | ... |
@pytest.mark.parametrize("entry", [
    "not an object",
    {"id": "e1"},
    {"id": "e1", "published": "2024-05-01T08:30:00", "width": 1920, "height": 1080,
     "title": "plain string", "description": {}, "views": {}, "likes": {}, "preview": {}},
])
def test_malformed_v2_entry_errors(run_cli, make_vault, legacy, workdir, entry):
    make_vault(legacy.v2_catalog(episodes=[entry]))
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert catalog_path(workdir).read_text(encoding="utf-8") == before


# Spec: | Malformed v1 or v2 entry data | ... | Context: `sync` reports it too,
# before touching the network.
def test_malformed_v2_entry_fails_sync(run_cli, make_vault, legacy, source, workdir):
    make_vault(legacy.v2_catalog(episodes=["not an object"]))
    before = catalog_path(workdir).read_text(encoding="utf-8")
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert catalog_path(workdir).read_text(encoding="utf-8") == before
    assert not backup_path(workdir).exists()


# Spec: Version 1 Catalog Schema | `entries` | array |
# Context: a v1 catalog whose `entries` is not an array is malformed.
def test_v1_entries_must_be_an_array(run_cli, make_vault, legacy, workdir):
    catalog = legacy.v1_catalog()
    catalog["entries"] = {"e1": {}}
    make_vault(catalog)
    result = run_cli("migrate", "vault")
    assert result.returncode != 0


# Spec: Version 1 Catalog Schema | `source_id` | string |
# Context: without it the required source derivation is impossible.
@pytest.mark.parametrize("catalog_patch", [{}, {"source_id": 5}])
def test_v1_requires_string_source_id(run_cli, make_vault, legacy, workdir, catalog_patch):
    catalog = legacy.v1_catalog(entries=[legacy.v1_entry("e1")])
    del catalog["source_id"]
    catalog.update(catalog_patch)
    make_vault(catalog)
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert result.stderr.strip() != ""


# Spec: Version 2 Catalog Schema | `source` | string | Full source URL |
def test_v2_requires_string_source(run_cli, make_vault, legacy, workdir):
    catalog = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")])
    del catalog["source"]
    make_vault(catalog)
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert result.stderr.strip() != ""


# Spec: | Missing vault | Error to stderr including `<name>`; exit non-zero |
# Context: a directory with no `catalog.json` cannot be version-detected.
def test_vault_without_catalog_errors(run_cli, workdir):
    (Path(workdir) / "vault").mkdir()
    result = run_cli("migrate", "vault")
    assert result.returncode != 0
    assert "vault" in result.stderr
