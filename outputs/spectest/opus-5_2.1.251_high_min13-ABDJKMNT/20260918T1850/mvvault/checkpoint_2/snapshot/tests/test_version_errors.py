"""Spec section: Version Handling Errors."""

import pytest

from conftest import (
    V1_EPOCH,
    V2_STAMP,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)

COMMANDS = ["migrate", "sync"]


def unchanged(directory, before):
    """The catalog still holds `before` and no backup was written."""
    return (directory / "catalog.json").read_bytes() == before and not (
        directory / "catalog.bak"
    ).exists()


# Spec: Missing `version` field | Error to stderr; exit non-zero; no migration; no modification
@pytest.mark.parametrize("command", COMMANDS)
def test_missing_version_field_errors(run, tmp_path, command):
    catalog = v1_catalog(entries=[v1_entry("e1")])
    del catalog["version"]
    directory = write_vault(tmp_path, catalog)
    before = (directory / "catalog.json").read_bytes()

    result = run(command, "vault")
    assert result.returncode != 0
    assert result.stderr.strip() and result.stdout == ""
    assert unchanged(directory, before)


# Spec: Non-integer `version` field | Version-related error to stderr; exit non-zero;
# no migration; no modification
@pytest.mark.parametrize("value", ["1", 1.5, None, True, [1]])
def test_non_integer_version_errors(run, tmp_path, value):
    directory = write_vault(tmp_path, {**v1_catalog(entries=[v1_entry("e1")]), "version": value})
    before = (directory / "catalog.json").read_bytes()

    result = run("migrate", "vault")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(directory, before)


# Spec: `version` greater than `3` | Version-related error to stderr; exit non-zero;
# no migration; no modification
@pytest.mark.parametrize("command", COMMANDS)
def test_version_above_three_errors(run, tmp_path, command):
    directory = write_vault(tmp_path, {**v2_catalog(episodes=[v2_entry("e1")]), "version": 4})
    before = (directory / "catalog.json").read_bytes()

    result = run(command, "vault")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(directory, before)


# Spec: `version` greater than `3` | ... (T18: integers below 1 are no more supported)
def test_version_below_one_errors(run, tmp_path):
    write_vault(tmp_path, {**v2_catalog(), "version": 0})
    result = run("migrate", "vault")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()


# Spec: Invalid JSON in `catalog.json` | Error to stderr; exit non-zero; no migration
@pytest.mark.parametrize("command", COMMANDS)
def test_invalid_json_errors(run, tmp_path, command):
    directory = write_vault(tmp_path, '{"version": 1, ')
    before = (directory / "catalog.json").read_bytes()

    result = run(command, "vault")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert unchanged(directory, before)


# Spec: Failure writing `catalog.bak` | Error to stderr; exit non-zero; abort migration;
# leave original `catalog.json` intact
def test_backup_write_failure_aborts_migration(run, tmp_path):
    directory = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    before = (directory / "catalog.json").read_bytes()
    (directory / "catalog.bak").mkdir()

    result = run("migrate", "vault")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert "Traceback" not in result.stderr
    assert (directory / "catalog.json").read_bytes() == before


# Spec: Malformed v1 or v2 entry data | Error to stderr; exit non-zero;
# leave `catalog.json` unchanged (T17)
@pytest.mark.parametrize(
    "entry",
    [
        "not-an-object",
        {**v1_entry("e1"), "id": 7},
        {**v1_entry("e1"), "width": "wide"},
        {**v1_entry("e1"), "title": "no history"},
        {**v1_entry("e1"), "views": {V1_EPOCH: "many"}},
        {**v1_entry("e1"), "title": {"yesterday": "bad key"}},
        {key: value for key, value in v1_entry("e1").items() if key != "preview"},
    ],
)
def test_malformed_v1_entry_errors(run, tmp_path, entry):
    directory = write_vault(tmp_path, v1_catalog(entries=[entry]))
    before = (directory / "catalog.json").read_bytes()

    result = run("migrate", "vault")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert unchanged(directory, before)


# Spec: Malformed v1 or v2 entry data | ... (T17)
@pytest.mark.parametrize(
    "entry",
    [
        [1, 2],
        {**v2_entry("e1"), "height": None},
        {**v2_entry("e1"), "likes": {V2_STAMP: "some"}},
        {**v2_entry("e1"), "description": {"not a date": "bad key"}},
        {key: value for key, value in v2_entry("e1").items() if key != "views"},
    ],
)
def test_malformed_v2_entry_errors(run, tmp_path, entry):
    directory = write_vault(tmp_path, v2_catalog(streams=[entry]))
    before = (directory / "catalog.json").read_bytes()

    result = run("migrate", "vault")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert unchanged(directory, before)


# Spec: Malformed v1 or v2 entry data | ... (a v1 catalog with no `entries` array at all)
def test_v1_catalog_without_entries_errors(run, tmp_path):
    write_vault(tmp_path, {"version": 1, "source_id": "chan-1"})
    assert run("migrate", "vault").returncode != 0


# Spec: Version 1 Catalog Schema | `source_id` | string (T17: a v1 vault needs one)
def test_v1_catalog_without_source_id_errors(run, tmp_path):
    write_vault(tmp_path, {"version": 1, "entries": []})
    assert run("migrate", "vault").returncode != 0


# Spec: Version 2 Catalog Schema | `source` | string (T17)
def test_v2_catalog_without_source_errors(run, tmp_path):
    catalog = v2_catalog(episodes=[v2_entry("e1")])
    del catalog["source"]
    write_vault(tmp_path, catalog)
    assert run("migrate", "vault").returncode != 0


# Spec: Version 2 Catalog Schema | `episodes`/`streams`/`clips` arrays (T17)
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_catalog_missing_a_category_errors(run, tmp_path, category):
    catalog = v2_catalog(episodes=[v2_entry("e1")])
    del catalog[category]
    write_vault(tmp_path, catalog)
    assert run("migrate", "vault").returncode != 0


# Spec: ... no migration; no modification (a legacy vault is validated before any fetch)
def test_malformed_legacy_vault_is_rejected_without_fetching(run, tmp_path, source):
    write_vault(tmp_path, v2_catalog(episodes=["bad"], source=source.url))
    assert run("sync", "vault").returncode != 0
    assert source.request_count == 0
