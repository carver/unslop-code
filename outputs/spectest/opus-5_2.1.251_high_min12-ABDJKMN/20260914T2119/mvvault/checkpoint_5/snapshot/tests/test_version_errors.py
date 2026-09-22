"""Spec: Version Handling Errors."""
import json
import os
import stat

import pytest

from conftest import (EPOCH_A, ISO_A, backup_path, catalog_bytes, catalog_path,
                      make_entry, make_v1_catalog, make_v1_entry,
                      make_v2_catalog, make_v2_entry, make_v3_catalog,
                      make_v3_entry, read_catalog)

# Commands that read a vault and so must reject an unusable catalog.
READERS = ["migrate", "sync", "digest"]


# Spec: "| Missing `version` field | Error to stderr; exit non-zero; no
# migration; no modification |"
@pytest.mark.parametrize("command", READERS)
def test_missing_version_field_errors(run, make_vault, command):
    catalog = make_v1_catalog()
    del catalog["version"]
    make_vault(catalog)
    res = run(command, "vault")
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# Spec: "Missing `version` field | ... **no migration; no modification**"
def test_missing_version_field_leaves_catalog_untouched(run, tmp_path, make_vault):
    catalog = make_v1_catalog()
    del catalog["version"]
    make_vault(catalog)
    before = catalog_bytes(tmp_path)
    run("migrate", "vault")
    assert catalog_bytes(tmp_path) == before
    assert not os.path.exists(backup_path(tmp_path))


# Spec: "| Non-integer `version` field | Version-related error to stderr; exit
# non-zero; no migration; no modification |"
@pytest.mark.parametrize("value", ["3", 3.5, 1.0, True, None, [3], {"v": 3}])
def test_non_integer_version_errors(run, make_vault, value):
    catalog = make_v1_catalog()
    catalog["version"] = value
    make_vault(catalog)
    res = run("migrate", "vault")
    assert res.returncode != 0


# Spec: "Non-integer `version` field | **Version-related error** to stderr ..."
def test_non_integer_version_error_mentions_version(run, make_vault):
    catalog = make_v1_catalog()
    catalog["version"] = "1"
    make_vault(catalog)
    res = run("migrate", "vault")
    assert "version" in res.stderr.lower()


# Spec: "Non-integer `version` field | ... no migration; no modification"
def test_non_integer_version_leaves_catalog_untouched(run, tmp_path, make_vault):
    catalog = make_v1_catalog()
    catalog["version"] = "1"
    make_vault(catalog)
    before = catalog_bytes(tmp_path)
    run("migrate", "vault")
    assert catalog_bytes(tmp_path) == before
    assert not os.path.exists(backup_path(tmp_path))


# Spec: "| `version` greater than `3` | Version-related error to stderr; exit
# non-zero; no migration; no modification |"
@pytest.mark.parametrize("value", [4, 5, 99])
@pytest.mark.parametrize("command", READERS)
def test_version_above_three_errors(run, make_vault, value, command):
    catalog = make_v3_catalog(episodes=[make_v3_entry()])
    catalog["version"] = value
    make_vault(catalog)
    res = run(command, "vault")
    assert res.returncode != 0
    assert "version" in res.stderr.lower()


# Spec: "`version` greater than `3` | ... no migration; no modification"
def test_version_above_three_leaves_catalog_untouched(run, tmp_path, make_vault):
    catalog = make_v3_catalog(episodes=[make_v3_entry()])
    catalog["version"] = 4
    make_vault(catalog)
    before = catalog_bytes(tmp_path)
    run("migrate", "vault")
    assert catalog_bytes(tmp_path) == before
    assert not os.path.exists(backup_path(tmp_path))


# Spec: the Supported Versions table lists `1`, `2` and `3` only, so a version
# below `1` is unsupported too (see AMBIGUITIES T14).
@pytest.mark.parametrize("value", [0, -1])
def test_version_below_one_errors(run, make_vault, value):
    catalog = make_v1_catalog()
    catalog["version"] = value
    make_vault(catalog)
    res = run("migrate", "vault")
    assert res.returncode != 0
    assert "version" in res.stderr.lower()


# Spec: "| Invalid JSON in `catalog.json` | Error to stderr; exit non-zero; no
# migration |"
@pytest.mark.parametrize("command", READERS)
def test_invalid_json_errors(run, make_raw_vault, command):
    make_raw_vault('{"version": 1, "entries": [')
    res = run(command, "vault")
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# Spec: "Invalid JSON in `catalog.json` | ... **no migration**"
def test_invalid_json_writes_nothing(run, tmp_path, make_raw_vault):
    make_raw_vault("not json at all")
    run("migrate", "vault")
    with open(catalog_path(tmp_path), "r", encoding="utf-8") as fh:
        assert fh.read() == "not json at all"
    assert not os.path.exists(backup_path(tmp_path))


# Spec: "Invalid JSON in `catalog.json` | ..." -- a JSON document that is not an
# object cannot declare a version either.
def test_non_object_json_errors(run, make_raw_vault):
    make_raw_vault("[1, 2, 3]")
    assert run("migrate", "vault").returncode != 0


# Spec: "| Failure writing `catalog.bak` | Error to stderr; exit non-zero; abort
# migration; leave original `catalog.json` intact |"
# Context: a directory at `catalog.bak` makes the copy fail.
def test_backup_write_failure_aborts_migration(run, tmp_path, make_vault):
    make_vault(make_v1_catalog())
    os.mkdir(backup_path(tmp_path))
    before = catalog_bytes(tmp_path)

    res = run("migrate", "vault")
    assert res.returncode != 0
    assert res.stderr.strip() != ""
    assert catalog_bytes(tmp_path) == before
    assert read_catalog(tmp_path)["version"] == 1


# Spec: "Failure writing `catalog.bak` | ... abort migration; leave original
# `catalog.json` intact" -- also when the failure happens during a `sync`.
def test_backup_write_failure_during_sync_leaves_catalog(run, source, tmp_path,
                                                         make_vault):
    make_vault(make_v2_catalog(source=source.url,
                               episodes=[make_v2_entry(id="e1")]))
    os.mkdir(backup_path(tmp_path))
    source.serve(episodes=[make_entry(id="e1")])
    before = catalog_bytes(tmp_path)

    res = run("sync", "vault")
    assert res.returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "| Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave
# `catalog.json` unchanged |" -- v1 entry that is not an object.
def test_malformed_v1_entry_not_an_object(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=["not-an-entry"]))
    before = catalog_bytes(tmp_path)
    res = run("migrate", "vault")
    assert res.returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | ..." -- a missing required field
# (see AMBIGUITIES T15).
@pytest.mark.parametrize("field", ["id", "published", "width", "height",
                                   "title", "description", "views", "likes",
                                   "preview"])
def test_malformed_v1_entry_missing_field(run, tmp_path, make_vault, field):
    entry = make_v1_entry()
    del entry[field]
    make_vault(make_v1_catalog(entries=[entry]))
    before = catalog_bytes(tmp_path)
    res = run("migrate", "vault")
    assert res.returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | ..." -- a field with the wrong type.
@pytest.mark.parametrize("field,value", [
    ("id", 7),
    ("published", 20240501),
    ("width", "1920"),
    ("height", None),
    ("title", "not a history object"),
    ("views", [1, 2]),
])
def test_malformed_v1_entry_wrong_type(run, tmp_path, make_vault, field, value):
    entry = make_v1_entry()
    entry[field] = value
    make_vault(make_v1_catalog(entries=[entry]))
    before = catalog_bytes(tmp_path)
    assert run("migrate", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | ..." -- v1 history keys that are not
# UNIX-epoch seconds cannot be converted.
@pytest.mark.parametrize("key", ["2024-06-15T09:40:00", "yesterday", ""])
def test_malformed_v1_history_key(run, tmp_path, make_vault, key):
    make_vault(make_v1_catalog(entries=[make_v1_entry(title={key: "A"})]))
    before = catalog_bytes(tmp_path)
    assert run("migrate", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | ..." -- v1 history values of the wrong
# type.
@pytest.mark.parametrize("field,history", [
    ("title", {EPOCH_A: 5}),
    ("views", {EPOCH_A: "10"}),
    ("likes", {EPOCH_A: "1"}),
    ("preview", {EPOCH_A: None}),
])
def test_malformed_v1_history_values(run, tmp_path, make_vault, field, history):
    entry = make_v1_entry()
    entry[field] = history
    make_vault(make_v1_catalog(entries=[entry]))
    before = catalog_bytes(tmp_path)
    assert run("migrate", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | ..." -- the v1 catalog fields
# themselves: `source_id` must be a string and `entries` an array.
@pytest.mark.parametrize("mutate", [
    lambda c: c.pop("source_id"),
    lambda c: c.update(source_id=42),
    lambda c: c.pop("entries"),
    lambda c: c.update(entries={"e1": {}}),
])
def test_malformed_v1_catalog_fields(run, tmp_path, make_vault, mutate):
    catalog = make_v1_catalog()
    mutate(catalog)
    make_vault(catalog)
    before = catalog_bytes(tmp_path)
    assert run("migrate", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | ..." -- v2 entries are checked the
# same way, in every category.
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_malformed_v2_entry_in_any_category(run, tmp_path, make_vault, category):
    entry = make_v2_entry()
    del entry["preview"]
    catalog = make_v2_catalog(episodes=[], streams=[], clips=[])
    catalog[category] = [entry]
    make_vault(catalog)
    before = catalog_bytes(tmp_path)
    assert run("migrate", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | ..." -- v2 history keys must be ISO
# 8601 datetimes (see AMBIGUITIES T19).
@pytest.mark.parametrize("key", ["1718444400", "not-a-date"])
def test_malformed_v2_history_key(run, tmp_path, make_vault, key):
    make_vault(make_v2_catalog(episodes=[make_v2_entry(title={key: "A"})]))
    before = catalog_bytes(tmp_path)
    assert run("migrate", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | ..." -- a v2 catalog missing a
# category array (see AMBIGUITIES T16).
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_catalog_missing_category(run, tmp_path, make_vault, category):
    catalog = make_v2_catalog()
    del catalog[category]
    make_vault(catalog)
    before = catalog_bytes(tmp_path)
    assert run("migrate", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before


# Spec: "Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave
# `catalog.json` unchanged |" -- `sync` refuses before touching the source too.
def test_malformed_legacy_entry_fails_sync(run, source, tmp_path, make_vault):
    entry = make_v2_entry()
    del entry["title"]
    make_vault(make_v2_catalog(source=source.url, episodes=[entry]))
    before = catalog_bytes(tmp_path)
    assert run("sync", "vault").returncode != 0
    assert catalog_bytes(tmp_path) == before
