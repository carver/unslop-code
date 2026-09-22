"""Spec section: `init` Command / `init` Catalog File / `catalog.json` Root Schema."""

import json

from conftest import read_catalog

URL = "http://example.test/feed.json"


# Phrase: "Syntax `python mvault.py init <name> <url>`" + "Vault directory `<name>/`"
def test_init_creates_vault_directory(run_cli, tmp_path):
    assert run_cli("init", "demo", URL).returncode == 0
    assert (tmp_path / "demo").is_dir()


# Phrase: "Catalog path | `<name>/catalog.json`"
def test_init_creates_catalog_at_expected_path(run_cli, tmp_path):
    run_cli("init", "demo", URL)
    assert (tmp_path / "demo" / "catalog.json").is_file()


# Phrase: "New vaults must start with the exact category layout below."
def test_init_catalog_matches_required_layout(run_cli, tmp_path):
    run_cli("init", "demo", URL)
    assert read_catalog(tmp_path / "demo") == {
        "version": 3,
        "source": URL,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


# Phrase: "`version` | integer | `3`"
def test_catalog_version_is_integer_three(run_cli, tmp_path):
    run_cli("init", "demo", URL)
    version = read_catalog(tmp_path / "demo")["version"]
    assert version == 3 and isinstance(version, int) and not isinstance(version, bool)


# Phrase: "`source` | string | Source URL passed to `init`"
def test_catalog_source_is_the_url_passed_to_init(run_cli, tmp_path):
    other = "https://videos.example.test/api/v2/items?tag=a%20b"
    run_cli("init", "other", other)
    assert read_catalog(tmp_path / "other")["source"] == other


# Phrase: "Success effect | Create new vault with empty catalog"
def test_init_categories_start_empty(run_cli, tmp_path):
    run_cli("init", "demo", URL)
    catalog = read_catalog(tmp_path / "demo")
    assert catalog["episodes"] == [] and catalog["streams"] == [] and catalog["clips"] == []


# Phrase: "Existing directory | Error to stderr including `<name>`; exit non-zero"
def test_init_on_existing_directory_errors_with_name(run_cli, tmp_path):
    (tmp_path / "demo").mkdir()
    result = run_cli("init", "demo", URL)
    assert result.returncode != 0
    assert "demo" in result.stderr


# Phrase: "no modification of existing data"
def test_init_on_existing_directory_leaves_data_untouched(run_cli, tmp_path):
    vault = tmp_path / "demo"
    vault.mkdir()
    existing = vault / "catalog.json"
    existing.write_text(json.dumps({"version": 3, "source": "kept", "episodes": [], "streams": [], "clips": []}))
    keepsake = vault / "notes.txt"
    keepsake.write_text("keep me")

    assert run_cli("init", "demo", "http://other.test/feed.json").returncode != 0
    assert json.loads(existing.read_text())["source"] == "kept"
    assert keepsake.read_text() == "keep me"


# Phrase: "Existing directory" - an existing *file* named <name> is not a usable vault directory
def test_init_when_name_is_an_existing_file(run_cli, tmp_path):
    (tmp_path / "demo").write_text("not a vault")
    result = run_cli("init", "demo", URL)
    assert result.returncode != 0
    assert "demo" in result.stderr


# Phrase: "`python mvault.py init <name> <url>`" - both arguments are required
def test_init_requires_both_arguments(run_cli):
    result = run_cli("init", "demo")
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()
