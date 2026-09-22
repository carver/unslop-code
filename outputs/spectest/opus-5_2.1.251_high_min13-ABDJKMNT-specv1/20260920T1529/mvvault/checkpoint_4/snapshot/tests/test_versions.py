"""Spec sections: Supported Versions / Multi-Version Loading / Version Handling Errors."""

import json

import pytest

from conftest import (
    V1_KEY,
    read_catalog,
    run_cli,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)


def catalog_bytes(vault):
    return (vault / "catalog.json").read_bytes()


# Supported Versions: "`1` | Supported" — a v1 catalog is readable by a command
# that reads a vault, rather than being rejected as an unsupported version.
def test_version_1_catalog_is_supported(tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]))
    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode == 0, result.stderr


# Supported Versions: "`2` | Supported".
def test_version_2_catalog_is_supported(tmp_path):
    write_vault(tmp_path, v2_catalog("https://example.com/feed", [v2_entry("e1")]))
    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode == 0, result.stderr


# Supported Versions: "`3` | Native format" — a v3 vault created by `init` keeps
# working with no migration involved.
def test_version_3_catalog_is_the_native_format(vault):
    assert read_catalog(vault)["version"] == 3
    assert run_cli("migrate", "demo", cwd=vault.parent).returncode == 0


# Multi-Version Loading: "Load trigger | Any command that reads a vault
# (`sync`, `serve`, `digest`, and future commands)" — of the commands that
# exist, `sync` and `migrate` both read legacy catalogs.
@pytest.mark.parametrize("command", ["sync", "migrate"])
def test_legacy_catalogs_load_for_every_reading_command(tmp_path, source, command):
    write_vault(tmp_path, v2_catalog(source.url, [v2_entry("e1")]))
    result = run_cli(command, "demo", cwd=tmp_path)
    assert result.returncode == 0, result.stderr


# Multi-Version Loading: "Version detection | Read `version` field from
# `catalog.json`" — the field, not the shape, selects the reader: a catalog
# whose body is v2-shaped but declares version 3 is read as v3 and left alone.
def test_version_field_selects_the_reader(tmp_path, source):
    body = v2_catalog(source.url, [v2_entry("e1")])
    vault = write_vault(tmp_path, {**body, "version": 3})
    before = catalog_bytes(vault)

    assert run_cli("migrate", "demo", cwd=tmp_path).returncode == 0
    assert catalog_bytes(vault) == before


# Multi-Version Loading: "In-memory representation | All versions are usable by
# every command" — a v1 catalog reaches `sync` as a v3 catalog, so the sync
# runs against the derived source rather than failing on the legacy layout.
def test_version_1_catalog_is_usable_by_sync(tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")], source_id="chan"))
    result = run_cli("sync", "demo", cwd=tmp_path)
    assert "https://media.example.com/channel/chan" in result.stderr


# Multi-Version Loading: "Read-only access | Loading a v1 or v2 catalog for a
# read-only operation does not rewrite `catalog.json`" — a sync that fails
# before its write is the observable read-only load.
def test_read_only_load_does_not_rewrite_the_catalog(tmp_path, source):
    vault = write_vault(tmp_path, v2_catalog(source.url, [v2_entry("e1")]))
    before = catalog_bytes(vault)
    source.serve_raw("not json at all")

    assert run_cli("sync", "demo", cwd=tmp_path).returncode != 0
    assert catalog_bytes(vault) == before
    assert not (vault / "catalog.bak").exists()


# Version Handling Errors: "Missing `version` field | Error to stderr; exit
# non-zero; no migration; no modification".
def test_missing_version_field_is_an_error(tmp_path):
    catalog = v1_catalog([v1_entry("e1")])
    del catalog["version"]
    vault = write_vault(tmp_path, catalog)
    before = catalog_bytes(vault)

    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert catalog_bytes(vault) == before
    assert not (vault / "catalog.bak").exists()


# Version Handling Errors: "Non-integer `version` field | Version-related error
# to stderr; exit non-zero; no migration; no modification".
@pytest.mark.parametrize("version", ["3", 3.5, True, None, [3]], ids=str)
def test_non_integer_version_is_a_version_error(tmp_path, version):
    vault = write_vault(tmp_path, {**v1_catalog([v1_entry("e1")]), "version": version})
    before = catalog_bytes(vault)

    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert catalog_bytes(vault) == before
    assert not (vault / "catalog.bak").exists()


# Version Handling Errors: "`version` greater than `3` | Version-related error
# to stderr; exit non-zero; no migration; no modification".
def test_version_above_three_is_a_version_error(tmp_path, source):
    vault = write_vault(tmp_path, {**v2_catalog(source.url), "version": 4})
    before = catalog_bytes(vault)

    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert catalog_bytes(vault) == before


# Version Handling Errors: "`version` greater than `3`" — `sync` refuses the
# same catalog, and refuses it before touching the vault.
def test_sync_refuses_a_future_version(tmp_path, source):
    vault = write_vault(tmp_path, {**v2_catalog(source.url), "version": 9})
    before = catalog_bytes(vault)

    assert run_cli("sync", "demo", cwd=tmp_path).returncode != 0
    assert catalog_bytes(vault) == before
    assert not (vault / "catalog.bak").exists()


# Version Handling Errors: "Invalid JSON in `catalog.json` | Error to stderr;
# exit non-zero; no migration".
def test_invalid_json_is_an_error(tmp_path):
    vault = write_vault(tmp_path, v1_catalog())
    (vault / "catalog.json").write_text("{not json")

    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert not (vault / "catalog.bak").exists()


# Version Handling Errors: "Failure writing `catalog.bak` | Error to stderr;
# exit non-zero; abort migration; leave original `catalog.json` intact" — the
# backup path is occupied by a directory, so copying onto it fails.
def test_backup_write_failure_aborts_the_migration(tmp_path):
    vault = write_vault(tmp_path, v1_catalog([v1_entry("e1")]))
    (vault / "catalog.bak").mkdir()
    before = catalog_bytes(vault)

    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert catalog_bytes(vault) == before


# Version Handling Errors: "Malformed v1 or v2 entry data | Error to stderr;
# exit non-zero; leave `catalog.json` unchanged".
@pytest.mark.parametrize(
    "entry",
    [
        {"id": "e1"},
        v1_entry("e1", width="1920"),
        v1_entry("e1", title="just text"),
        v1_entry("e1", views={V1_KEY: "ten"}),
        v1_entry("e1", likes={V1_KEY: 1.5}),
        v1_entry("e1", preview={}),
        v1_entry("e1", key="not-an-epoch"),
        "a string, not an entry",
    ],
    ids=["missing-fields", "static-type", "flat-field", "value-type",
         "float-value", "empty-history", "bad-key", "not-an-object"],
)
def test_malformed_v1_entry_data_is_an_error(tmp_path, entry):
    vault = write_vault(tmp_path, v1_catalog([entry]))
    before = catalog_bytes(vault)

    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert catalog_bytes(vault) == before


# Version Handling Errors: "Malformed v1 or v2 entry data" — the same applies
# to entries in any v2 category, including non-ISO history keys.
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_malformed_v2_entry_data_is_an_error(tmp_path, source, category):
    catalog = v2_catalog(source.url)
    catalog[category] = [v2_entry("e1", key="whenever")]
    vault = write_vault(tmp_path, catalog)
    before = catalog_bytes(vault)

    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert catalog_bytes(vault) == before


# Version Handling Errors: a legacy catalog missing the fields its own version
# declares (`source_id`/`entries` for v1) is rejected, not half-migrated.
@pytest.mark.parametrize("field", ["source_id", "entries"])
def test_incomplete_v1_catalog_is_an_error(tmp_path, field):
    catalog = v1_catalog([v1_entry("e1")])
    del catalog[field]
    vault = write_vault(tmp_path, catalog)

    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert json.loads((vault / "catalog.json").read_text())["version"] == 1
