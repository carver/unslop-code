"""Spec section: Version Handling Errors."""
import json
import os
import re
import stat

import pytest
from conftest import (EPOCH, V1_SOURCE_PREFIX, entry, has_backup, make_vault,
                      payload, read_bytes, read_catalog, v1_catalog, v1_entry,
                      v2_catalog, v2_entry, v3_catalog, v3_entry, write_raw)


def unchanged(vault, before):
    return read_bytes(vault / "catalog.json") == before


# Phrase: "Missing `version` field | Error to stderr; exit non-zero; no
#          migration; no modification"
def test_missing_version_field(run, tmp_path):
    catalog = v2_catalog(episodes=[v2_entry("e1")])
    del catalog["version"]
    vault = make_vault(tmp_path, "v", catalog)
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert unchanged(vault, before)
    assert not has_backup(vault)


# Phrase: "Missing `version` field | ... no migration; no modification"
# Context: the same holds for `sync`.
def test_missing_version_field_blocks_sync(run, source, tmp_path):
    catalog = v2_catalog(source=source.url, episodes=[v2_entry("e1")])
    del catalog["version"]
    vault = make_vault(tmp_path, "v", catalog)
    before = read_bytes(vault / "catalog.json")
    result = run("sync", "v")
    assert result.returncode != 0
    assert unchanged(vault, before)
    assert not has_backup(vault)


# Phrase: "Non-integer `version` field | Version-related error to stderr; exit
#          non-zero; no migration; no modification"
@pytest.mark.parametrize("value", ["3", 3.5, True, None, [3], {"n": 3}])
def test_non_integer_version(run, tmp_path, value):
    catalog = v3_catalog(episodes=[v3_entry("e1")])
    catalog["version"] = value
    vault = make_vault(tmp_path, "v", catalog)
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(vault, before)
    assert not has_backup(vault)


# Phrase: "`version` greater than `3` | Version-related error to stderr; exit
#          non-zero; no migration; no modification"
@pytest.mark.parametrize("value", [4, 99])
def test_version_greater_than_three(run, tmp_path, value):
    catalog = v3_catalog(episodes=[v3_entry("e1")])
    catalog["version"] = value
    vault = make_vault(tmp_path, "v", catalog)
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(vault, before)
    assert not has_backup(vault)


# Phrase: "`version` greater than `3` | ... no migration; no modification"
# Context: `sync` refuses a future-version vault too, before any fetch.
def test_version_greater_than_three_blocks_sync(run, source, tmp_path):
    catalog = v3_catalog(source=source.url, episodes=[v3_entry("e1")])
    catalog["version"] = 4
    vault = make_vault(tmp_path, "v", catalog)
    before = read_bytes(vault / "catalog.json")
    result = run("sync", "v")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(vault, before)
    assert source.requests == []


# Phrase: Version Handling Errors — versions below the supported range are
# rejected as version errors too. See AMBIGUITIES.md T19.
@pytest.mark.parametrize("value", [0, -1])
def test_version_below_one(run, tmp_path, value):
    catalog = v3_catalog()
    catalog["version"] = value
    vault = make_vault(tmp_path, "v", catalog)
    result = run("migrate", "v")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert not has_backup(vault)


# Phrase: "Invalid JSON in `catalog.json` | Error to stderr; exit non-zero; no
#          migration"
def test_invalid_json_catalog(run, tmp_path):
    vault = tmp_path / "v"
    vault.mkdir()
    write_raw(vault, '{"version": 1, "entries": [')
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert unchanged(vault, before)
    assert not has_backup(vault)


# Phrase: "Invalid JSON in `catalog.json` | ... no migration"
# Context: a catalog that parses but is not an object is rejected as well.
def test_non_object_catalog_root(run, tmp_path):
    vault = tmp_path / "v"
    vault.mkdir()
    write_raw(vault, "[1, 2, 3]")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert not has_backup(vault)


# Phrase: "Failure writing `catalog.bak` | Error to stderr; exit non-zero;
#          abort migration; leave original `catalog.json` intact"
# Context: a directory at `catalog.bak` makes the copy impossible.
def test_backup_write_failure_aborts_migration(run, tmp_path):
    original = v1_catalog(entries=[v1_entry("e1")])
    vault = make_vault(tmp_path, "v", original)
    (vault / "catalog.bak").mkdir()
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert unchanged(vault, before)
    assert read_catalog(vault) == original


# Phrase: "Malformed v1 or v2 entry data | Error to stderr; exit non-zero;
#          leave `catalog.json` unchanged"
# Context: a v1 history object whose key is not epoch seconds cannot be
# converted. See AMBIGUITIES.md T15.
def test_malformed_v1_history_key(run, tmp_path):
    item = v1_entry("e1")
    item["title"] = {"yesterday": "T"}
    vault = make_vault(tmp_path, "v", v1_catalog(entries=[item]))
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert unchanged(vault, before)
    assert not has_backup(vault)


# Phrase: "Malformed v1 or v2 entry data | ..."
# Context: a history field that is not an object at all.
def test_malformed_v1_history_object(run, tmp_path):
    item = v1_entry("e1")
    item["views"] = 12
    vault = make_vault(tmp_path, "v", v1_catalog(entries=[item]))
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert unchanged(vault, before)


# Phrase: "Malformed v1 or v2 entry data | ..."
# Context: an entry that is not an object.
def test_malformed_v1_entry_not_an_object(run, tmp_path):
    vault = make_vault(tmp_path, "v", v1_catalog(entries=["nope"]))
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert unchanged(vault, before)


# Phrase: "Malformed v1 or v2 entry data | ..."
# Context: an entry without a usable `id`.
def test_malformed_v1_entry_without_id(run, tmp_path):
    item = v1_entry("e1")
    del item["id"]
    vault = make_vault(tmp_path, "v", v1_catalog(entries=[item]))
    result = run("migrate", "v")
    assert result.returncode != 0


# Phrase: "Malformed v1 or v2 entry data | ..."
# Context: v1 `entries` missing or not an array.
def test_malformed_v1_entries_container(run, tmp_path):
    catalog = v1_catalog()
    catalog["entries"] = {"e1": {}}
    vault = make_vault(tmp_path, "v", catalog)
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert unchanged(vault, before)


# Phrase: "Malformed v1 or v2 entry data | ..."
# Context: v1 `source_id` missing or not a string.
def test_malformed_v1_source_id(run, tmp_path):
    catalog = v1_catalog()
    catalog["source_id"] = 42
    vault = make_vault(tmp_path, "v", catalog)
    result = run("migrate", "v")
    assert result.returncode != 0


# Phrase: "Malformed v1 or v2 entry data | ..."
# Context: a v2 history value of the wrong type.
def test_malformed_v2_history_value(run, tmp_path):
    item = v2_entry("e1")
    item["views"] = {"2024-06-15T09:40:00": "many"}
    vault = make_vault(tmp_path, "v", v2_catalog(episodes=[item]))
    before = read_bytes(vault / "catalog.json")
    result = run("migrate", "v")
    assert result.returncode != 0
    assert unchanged(vault, before)
    assert not has_backup(vault)


# Phrase: "Malformed v1 or v2 entry data | ..."
# Context: a v2 category that is not an array.
def test_malformed_v2_category(run, tmp_path):
    catalog = v2_catalog()
    catalog["clips"] = "none"
    vault = make_vault(tmp_path, "v", catalog)
    result = run("migrate", "v")
    assert result.returncode != 0


# Phrase: "Malformed v1 or v2 entry data | ... leave `catalog.json` unchanged"
# Context: the same failure stops `sync` before it writes.
def test_malformed_v2_entry_blocks_sync(run, source, tmp_path):
    item = v2_entry("e1")
    item["title"] = "not a history object"
    vault = make_vault(tmp_path, "v", v2_catalog(source=source.url,
                                                 episodes=[item]))
    before = read_bytes(vault / "catalog.json")
    result = run("sync", "v")
    assert result.returncode != 0
    assert unchanged(vault, before)
    assert not has_backup(vault)


# Phrase: "Malformed v1 or v2 entry data | ..."
# Context: errors go to stderr, never stdout.
def test_malformed_entry_message_not_on_stdout(run, tmp_path):
    item = v1_entry("e1")
    item["title"] = {"soon": "T"}
    make_vault(tmp_path, "v", v1_catalog(entries=[item]))
    result = run("migrate", "v")
    assert result.stdout == ""
    assert result.stderr.strip()
