"""Spec: Supported Versions, the v1/v2 schemas, and Multi-Version Loading."""
import os

import pytest

from conftest import (EPOCH_A, EPOCH_B, ISO_A, ISO_B, V1_SOURCE_PREFIX,
                      backup_path, catalog_bytes, current, find_entry,
                      make_v1_catalog, make_v1_entry, make_v2_catalog,
                      make_v2_entry, make_v3_catalog, make_v3_entry,
                      read_catalog)


# Spec: "`mvault` supports transparent loading of legacy vault catalogs." +
# "Commands that read vault data must handle all supported versions without
# requiring prior migration."
# Context: a v1 catalog is readable with no `migrate` run first.
def test_v1_catalog_is_readable_without_prior_migration(run, make_vault):
    make_vault(make_v1_catalog())
    res = run("digest", "vault")
    assert res.returncode == 0, res


# Spec: "Commands that read vault data must handle all supported versions
# without requiring prior migration." -- version 2.
def test_v2_catalog_is_readable_without_prior_migration(run, make_vault):
    make_vault(make_v2_catalog())
    res = run("digest", "vault")
    assert res.returncode == 0, res


# Spec: "| `3` | Native format | ... |" -- the native version stays readable.
def test_v3_catalog_is_readable(run, make_vault):
    make_vault(make_v3_catalog(episodes=[make_v3_entry()]))
    res = run("digest", "vault")
    assert res.returncode == 0, res


# Spec: "| Version detection | Read `version` field from `catalog.json` |"
# Context: the declared version, not the shape, selects the reading.
@pytest.mark.parametrize("catalog", [
    make_v1_catalog(),
    make_v2_catalog(),
    make_v3_catalog(episodes=[make_v3_entry()]),
])
def test_version_field_selects_the_supported_reading(run, make_vault, catalog):
    make_vault(catalog)
    assert run("digest", "vault").returncode == 0


# Spec: "| Read-only access | Loading a v1 or v2 catalog for a read-only
# operation does **not** rewrite `catalog.json` |" -- version 1.
def test_read_only_load_of_v1_does_not_rewrite_catalog(run, tmp_path, make_vault):
    make_vault(make_v1_catalog())
    before = catalog_bytes(tmp_path)
    assert run("digest", "vault").returncode == 0
    assert catalog_bytes(tmp_path) == before
    assert read_catalog(tmp_path)["version"] == 1


# Spec: "Read-only access | Loading a v1 or v2 catalog for a read-only
# operation does **not** rewrite `catalog.json`" -- version 2.
def test_read_only_load_of_v2_does_not_rewrite_catalog(run, tmp_path, make_vault):
    make_vault(make_v2_catalog())
    before = catalog_bytes(tmp_path)
    assert run("digest", "vault").returncode == 0
    assert catalog_bytes(tmp_path) == before
    assert read_catalog(tmp_path)["version"] == 2


# Spec: "Read-only access ... does **not** rewrite `catalog.json`" -- a
# read-only load writes no backup either (nothing was written).
def test_read_only_load_writes_no_backup(run, tmp_path, make_vault):
    make_vault(make_v1_catalog())
    run("digest", "vault")
    assert not os.path.exists(backup_path(tmp_path))


# Spec: "| In-memory representation | All versions are usable by every command |"
# Context: the v1 flat `entries` list is visible as episodes to a reader.
def test_v1_entries_are_usable_in_memory(run, make_vault):
    make_vault(make_v1_catalog(entries=[make_v1_entry(id="a"),
                                        make_v1_entry(id="b")]))
    res = run("digest", "vault")
    assert res.returncode == 0, res
    assert "2" in res.stdout


# Spec: "| `1` | Supported | Flat `entries` list; `source_id`; UNIX-epoch
# history keys; no `removed`; no `annotations` |"
# Context: exactly that shape loads successfully.
def test_v1_shape_is_supported(run, make_vault):
    catalog = make_v1_catalog()
    assert "entries" in catalog and "source_id" in catalog
    assert "removed" not in catalog["entries"][0]
    assert "annotations" not in catalog["entries"][0]
    make_vault(catalog)
    assert run("migrate", "vault").returncode == 0


# Spec: "| `2` | Supported | Category arrays; full `source`; ISO 8601 history
# keys; no `removed`; no `annotations` |"
def test_v2_shape_is_supported(run, make_vault):
    catalog = make_v2_catalog()
    assert set(["episodes", "streams", "clips"]).issubset(catalog)
    assert "removed" not in catalog["episodes"][0]
    assert "annotations" not in catalog["episodes"][0]
    make_vault(catalog)
    assert run("migrate", "vault").returncode == 0


# Spec: Version 1 Entry Schema -- `likes` history values are "integer or
# `null`", so a null-valued v1 history loads.
def test_v1_null_likes_loads(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=[make_v1_entry(likes={EPOCH_A: None})]))
    assert run("migrate", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(entry["likes"]) is None


# Spec: Version 2 Entry Schema -- `likes` history values are "integer or `null`".
def test_v2_null_likes_loads(run, tmp_path, make_vault):
    make_vault(make_v2_catalog(episodes=[make_v2_entry(likes={ISO_A: None})]))
    assert run("migrate", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(entry["likes"]) is None


# Spec: "Version 1 history objects use string representations of UNIX epoch
# seconds as keys (e.g., `"1718444400"`)."
def test_v1_epoch_key_example_converts(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=[make_v1_entry(title={EPOCH_A: "A"})]))
    assert run("migrate", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert list(entry["title"]) == [ISO_A]


# Spec: "Chronological ordering is determined by numeric comparison of these
# values."
# Context: "999999999" sorts after "1000000000" as text but before it
# numerically, so the numerically newest value must win.
def test_v1_history_order_is_numeric_not_lexicographic(run, tmp_path, make_vault):
    history = {"999999999": "older", "1000000000": "newer"}
    make_vault(make_v1_catalog(entries=[make_v1_entry(title=history)]))
    assert run("migrate", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(entry["title"]) == "newer"


# Spec: "Chronological ordering is determined by numeric comparison" --
# ordering survives conversion for a multi-key integer history too.
def test_v1_numeric_order_survives_conversion(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=[
        make_v1_entry(views={EPOCH_A: 10, EPOCH_B: 20})]))
    assert run("migrate", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert entry["views"] == {ISO_A: 10, ISO_B: 20}
    assert current(entry["views"]) == 20


# Spec: "The full source URL for a version 1 vault is derived deterministically
# from `source_id`: https://media.example.com/channel/<source_id>"
@pytest.mark.parametrize("source_id", ["chan42", "abc", "A-b_9"])
def test_v1_source_derivation(run, tmp_path, make_vault, source_id):
    make_vault(make_v1_catalog(source_id=source_id))
    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path)["source"] == V1_SOURCE_PREFIX + source_id


# Spec: "All commands that need a source URL for a version 1 vault must use
# this derivation."
# Context: `sync` reaches for the derived URL (and reports it when it fails).
def test_sync_on_v1_uses_derived_source_url(run, make_vault):
    make_vault(make_v1_catalog(source_id="chan42"))
    res = run("sync", "vault")
    assert res.returncode != 0
    assert V1_SOURCE_PREFIX + "chan42" in res.stderr
