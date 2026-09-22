"""Spec sections: `init` Command / `init` Catalog File / root schema."""
import json
import os

from conftest import read_bytes, read_catalog

URL = "https://media.example.invalid/api/feed.json"


# Phrase: "Syntax | `python mvault.py init <name> <url>`" +
#         "Vault directory | `<name>/`" + "Catalog path | `<name>/catalog.json`"
def test_init_creates_vault_directory_and_catalog(run, tmp_path):
    result = run("init", "myvault", URL)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "myvault").is_dir()
    assert (tmp_path / "myvault" / "catalog.json").is_file()


# Phrase: "Success effect | Create new vault with empty catalog"
# Context: "New vaults must start with the exact category layout below."
def test_init_catalog_exact_layout(run, tmp_path):
    run("init", "myvault", URL)
    assert read_catalog(tmp_path / "myvault") == {
        "version": 3,
        "source": URL,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


# Phrase: "`version` | integer | `3`"
def test_catalog_version_is_integer_three(run, tmp_path):
    run("init", "myvault", URL)
    version = read_catalog(tmp_path / "myvault")["version"]
    assert version == 3 and isinstance(version, int) and not isinstance(version, bool)


# Phrase: "`source` | string | Source URL passed to `init`"
def test_catalog_source_is_the_url_passed_to_init(run, tmp_path):
    run("init", "other", "http://example.invalid/x?y=1&z=2")
    catalog = read_catalog(tmp_path / "other")
    assert catalog["source"] == "http://example.invalid/x?y=1&z=2"
    assert isinstance(catalog["source"], str)


# Phrase: "`episodes` / `streams` / `clips` | array | Entry objects"
# Context: a new vault's categories are empty arrays.
def test_catalog_categories_are_empty_arrays(run, tmp_path):
    run("init", "myvault", URL)
    catalog = read_catalog(tmp_path / "myvault")
    for category in ("episodes", "streams", "clips"):
        assert catalog[category] == [] and isinstance(catalog[category], list)


# Phrase: "Existing directory | Error to stderr including `<name>`; exit non-zero"
def test_init_existing_directory_errors_with_name(run, tmp_path):
    (tmp_path / "taken").mkdir()
    result = run("init", "taken", URL)
    assert result.returncode != 0
    assert "taken" in result.stderr


# Phrase: "Existing directory | ... no modification of existing data"
def test_init_existing_directory_leaves_data_untouched(run, tmp_path):
    vault = tmp_path / "taken"
    vault.mkdir()
    (vault / "catalog.json").write_text('{"version": 3, "keep": "me"}', encoding="utf-8")
    (vault / "extra.txt").write_text("hello", encoding="utf-8")
    before = {name: read_bytes(vault / name) for name in os.listdir(str(vault))}

    result = run("init", "taken", URL)

    assert result.returncode != 0
    after = {name: read_bytes(vault / name) for name in os.listdir(str(vault))}
    assert after == before


# Phrase: "Error to stderr including `<name>`"
# Context: the failure is reported on stderr, not stdout.
def test_init_error_goes_to_stderr(run, tmp_path):
    (tmp_path / "taken").mkdir()
    result = run("init", "taken", URL)
    assert "taken" not in result.stdout


# Phrase: "`catalog.json` Persistence: Backup trigger | Before every write to
#          existing `catalog.json`"
# Context: init writes a brand-new catalog, so there is nothing to back up.
def test_init_does_not_create_backup(run, tmp_path):
    run("init", "myvault", URL)
    assert not (tmp_path / "myvault" / "catalog.bak").exists()


# Phrase: "Catalog path | `<name>/catalog.json`"
# Context: nested/relative vault names resolve against the working directory.
def test_init_accepts_nested_name(run, tmp_path):
    (tmp_path / "parent").mkdir()
    result = run("init", os.path.join("parent", "child"), URL)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "parent" / "child" / "catalog.json").read_text())["source"] == URL
