"""`init` Command, `init` Catalog File and `catalog.json` Root Schema."""

import json

from conftest import read_catalog

URL = "https://example.invalid/media.json"


# Spec: Syntax | `python mvault.py init <name> <url>`; Vault directory | `<name>/`
def test_init_creates_vault_directory(run_cli, tmp_path):
    assert run_cli("init", "shows", URL).returncode == 0
    assert (tmp_path / "shows").is_dir()


# Spec: Catalog path | `<name>/catalog.json`
def test_init_creates_catalog_at_expected_path(run_cli, tmp_path):
    run_cli("init", "shows", URL)
    assert (tmp_path / "shows" / "catalog.json").is_file()


# Spec: Success effect | Create new vault with empty catalog
# Spec: New vaults must start with the exact category layout below.
def test_init_catalog_has_exact_layout(run_cli, tmp_path):
    run_cli("init", "shows", URL)
    assert read_catalog(tmp_path / "shows") == {
        "version": 3,
        "source": URL,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


# Spec: `version` | integer | `3`
def test_catalog_version_is_integer_three(run_cli, tmp_path):
    run_cli("init", "shows", URL)
    version = read_catalog(tmp_path / "shows")["version"]
    assert version == 3 and isinstance(version, int) and not isinstance(version, bool)


# Spec: `source` | string | Source URL passed to `init`
def test_catalog_source_is_the_given_url(run_cli, tmp_path):
    run_cli("init", "shows", "http://other.invalid/f.json")
    assert read_catalog(tmp_path / "shows")["source"] == "http://other.invalid/f.json"


# Spec: `episodes` / `streams` / `clips` | array | Entry objects for ... content
def test_catalog_categories_are_arrays(run_cli, tmp_path):
    run_cli("init", "shows", URL)
    catalog = read_catalog(tmp_path / "shows")
    assert [catalog["episodes"], catalog["streams"], catalog["clips"]] == [[], [], []]


# Spec: Existing directory | Error to stderr including `<name>`; exit non-zero
def test_init_on_existing_directory_errors_with_name(run_cli, tmp_path):
    (tmp_path / "shows").mkdir()
    result = run_cli("init", "shows", URL)
    assert result.returncode != 0
    assert "shows" in result.stderr


# Spec: Existing directory | ... no modification of existing data
def test_init_on_existing_directory_leaves_data_untouched(run_cli, tmp_path):
    vault = tmp_path / "shows"
    vault.mkdir()
    (vault / "catalog.json").write_text('{"version": 3, "source": "kept"}')
    (vault / "notes.txt").write_text("keep me")

    run_cli("init", "shows", URL)

    assert json.loads((vault / "catalog.json").read_text()) == {"version": 3, "source": "kept"}
    assert (vault / "notes.txt").read_text() == "keep me"


# Spec: `init` with existing vault directory | stderr | non-zero (nothing on stdout path)
def test_init_error_is_not_written_to_stdout(run_cli, tmp_path):
    (tmp_path / "shows").mkdir()
    result = run_cli("init", "shows", URL)
    assert "shows" not in result.stdout
