"""`mvault` Error Handling table."""

import json

import pytest

from conftest import source_entry


# Spec: `sync` with non-existent vault | stderr | non-zero | Message includes vault name
def test_sync_missing_vault_errors_with_name(run_cli):
    result = run_cli("sync", "ghost")
    assert result.returncode != 0
    assert "ghost" in result.stderr


# Spec: `sync` with non-existent vault ... (nothing is created)
def test_sync_missing_vault_creates_nothing(run_cli, tmp_path):
    run_cli("sync", "ghost")
    assert not (tmp_path / "ghost").exists()


# Spec: `sync` with invalid vault | stderr | non-zero | Message includes vault name
def test_sync_directory_without_catalog_errors_with_name(run_cli, tmp_path):
    (tmp_path / "broken").mkdir()
    result = run_cli("sync", "broken")
    assert result.returncode != 0
    assert "broken" in result.stderr


# Spec: `sync` with invalid vault (catalog.json is not JSON)
def test_sync_unparseable_catalog_errors_with_name(run_cli, tmp_path):
    vault = tmp_path / "broken"
    vault.mkdir()
    (vault / "catalog.json").write_text("{not json")
    result = run_cli("sync", "broken")
    assert result.returncode != 0
    assert "broken" in result.stderr


# Spec: `sync` with invalid vault (AMBIGUITIES T4: the root schema must be intact;
# a `version` of 1 or 2 is now a supported legacy layout, not an invalid vault)
@pytest.mark.parametrize(
    "catalog",
    [
        [],
        {},
        {"version": 3, "source": "http://x.invalid/f.json"},
        {"version": 3, "source": 5, "episodes": [], "streams": [], "clips": []},
        {"version": 3, "source": "http://x.invalid/f.json", "episodes": {}, "streams": [], "clips": []},
        {"version": 3, "source": "http://x.invalid/f.json", "episodes": [{"id": "a"}], "streams": [], "clips": []},
    ],
)
def test_sync_invalid_catalog_shapes_error_with_name(run_cli, tmp_path, catalog):
    vault = tmp_path / "broken"
    vault.mkdir()
    (vault / "catalog.json").write_text(json.dumps(catalog))
    result = run_cli("sync", "broken")
    assert result.returncode != 0
    assert "broken" in result.stderr


# Spec: `sync` with invalid vault ... (the broken catalog is left as it was)
def test_invalid_vault_is_left_unchanged(run_cli, tmp_path):
    vault = tmp_path / "broken"
    vault.mkdir()
    (vault / "catalog.json").write_text("{not json")
    run_cli("sync", "broken")
    assert (vault / "catalog.json").read_text() == "{not json"
    assert not (vault / "catalog.bak").exists()


# Spec: Source metadata fetch failure | stderr | non-zero | Error message
def test_fetch_failure_message_goes_to_stderr(run_cli, vault, source):
    source.status = 404
    result = run_cli("sync", "v")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Source metadata fetch failure ... malformed source entries are included
def test_malformed_entry_message_goes_to_stderr(run_cli, vault, source):
    source.payload = {"episodes": [source_entry("a", views="lots")], "streams": [], "clips": []}
    result = run_cli("sync", "v")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: No subcommand | stderr | non-zero | Usage text
def test_unknown_subcommand_errors(run_cli):
    result = run_cli("frobnicate")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Syntax | `python mvault.py init <name> <url>` (arity is enforced)
@pytest.mark.parametrize("args", [("init",), ("init", "only-name"), ("sync",)])
def test_missing_arguments_error(run_cli, args):
    result = run_cli(*args)
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Error messages never masquerade as success output
def test_errors_do_not_print_to_stdout(run_cli):
    result = run_cli("sync", "ghost")
    assert result.stdout == ""
