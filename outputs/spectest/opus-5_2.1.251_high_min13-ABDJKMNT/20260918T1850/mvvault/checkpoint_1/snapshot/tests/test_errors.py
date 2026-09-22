"""Spec sections: `sync` Command (invalid vault), `mvault` Error Handling."""

import json

import pytest

from conftest import payload, read_catalog, source_entry

VALID_CATALOG = {
    "version": 3,
    "source": "http://example.invalid/source.json",
    "episodes": [],
    "streams": [],
    "clips": [],
}


def write_catalog(tmp_path, catalog, name="vault"):
    """Create `<name>/catalog.json` by hand, bypassing `init`."""
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    body = catalog if isinstance(catalog, str) else json.dumps(catalog)
    (directory / "catalog.json").write_text(body)
    return directory


# Spec: `init` with existing vault directory | stderr | non-zero | Message includes vault name
def test_init_error_names_the_vault(run, tmp_path):
    (tmp_path / "archive").mkdir()
    result = run("init", "archive", "http://example.invalid/s.json")
    assert result.returncode != 0
    assert "archive" in result.stderr


# Spec: `sync` with non-existent vault | stderr | non-zero | Message includes vault name
def test_sync_missing_vault_names_the_vault(run):
    result = run("sync", "nowhere")
    assert result.returncode != 0
    assert "nowhere" in result.stderr
    assert result.stdout == ""


# Spec: Missing or invalid vault | Error to stderr including `<name>`; exit non-zero
def test_sync_directory_without_catalog_errors(run, tmp_path):
    (tmp_path / "vault").mkdir()
    result = run("sync", "vault")
    assert result.returncode != 0
    assert "vault" in result.stderr


# Spec: `sync` with invalid vault | ... (T9: unparseable catalog)
def test_sync_unparseable_catalog_errors(run, tmp_path):
    write_catalog(tmp_path, "{broken")
    result = run("sync", "vault")
    assert result.returncode != 0
    assert "vault" in result.stderr


# Spec: `sync` with invalid vault | ... (T9: catalog must be a JSON object)
def test_sync_non_object_catalog_errors(run, tmp_path):
    write_catalog(tmp_path, "[]")
    result = run("sync", "vault")
    assert result.returncode != 0
    assert "vault" in result.stderr


# Spec: `sync` with invalid vault | ... (T9: required root fields)
@pytest.mark.parametrize("missing", ["version", "source", "episodes", "streams", "clips"])
def test_sync_catalog_missing_root_field_errors(run, tmp_path, missing):
    catalog = dict(VALID_CATALOG)
    del catalog[missing]
    write_catalog(tmp_path, catalog)

    result = run("sync", "vault")
    assert result.returncode != 0
    assert "vault" in result.stderr


# Spec: `sync` with invalid vault | ... (T9: root field types)
@pytest.mark.parametrize(
    "field,value",
    [("source", 42), ("episodes", {}), ("streams", "none"), ("clips", 0), ("version", "3")],
)
def test_sync_catalog_wrong_root_type_errors(run, tmp_path, field, value):
    write_catalog(tmp_path, {**VALID_CATALOG, field: value})

    result = run("sync", "vault")
    assert result.returncode != 0
    assert "vault" in result.stderr


# Spec: `version` | integer | `3` (T10: other versions are invalid vaults)
def test_sync_unsupported_version_errors(run, tmp_path):
    write_catalog(tmp_path, {**VALID_CATALOG, "version": 2})

    result = run("sync", "vault")
    assert result.returncode != 0
    assert "vault" in result.stderr


# Spec: Missing or invalid vault ... (vault validity is checked before fetching)
def test_invalid_vault_is_rejected_without_fetching(run, tmp_path, source):
    write_catalog(tmp_path, {**VALID_CATALOG, "source": source.url, "version": 99})
    assert run("sync", "vault").returncode != 0
    assert source.request_count == 0


# Spec: Source metadata fetch failure | stderr | non-zero | Error message
def test_fetch_failure_writes_to_stderr_only(run, source, vault):
    source.serve_raw("<html>oops</html>", status=502)
    result = run("sync", "vault")
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.strip()


# Spec: No subcommand | stderr | non-zero | Usage text
def test_no_subcommand_prints_usage_to_stderr(run):
    result = run()
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()


# Spec: Console command | `python mvault.py <subcommand> [args...]` (unknown subcommand)
def test_unknown_subcommand_errors(run):
    result = run("frobnicate")
    assert result.returncode != 0
    assert result.stderr.strip()


# Spec: Syntax | `python mvault.py sync <name>`
def test_sync_requires_a_vault_name(run):
    assert run("sync").returncode != 0


# Spec: Missing or invalid vault | Error ... (errors are messages, not tracebacks)
@pytest.mark.parametrize(
    "setup",
    ["missing", "no-catalog", "broken-json"],
)
def test_vault_errors_are_not_tracebacks(run, tmp_path, setup):
    if setup == "no-catalog":
        (tmp_path / "vault").mkdir()
    elif setup == "broken-json":
        write_catalog(tmp_path, "{")

    name = "vault" if setup != "missing" else "absent"
    result = run("sync", name)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


# Spec: Source metadata fetch failure ... (errors are messages, not tracebacks)
def test_fetch_errors_are_not_tracebacks(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", views=None)]))
    result = run("sync", "vault")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


# Spec: Success effect | Update catalog ... (a successful sync is silent on stderr)
def test_successful_sync_exits_zero(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    result = run("sync", "vault")
    assert result.returncode == 0
    assert result.stderr == ""
    assert read_catalog(vault)["episodes"]
