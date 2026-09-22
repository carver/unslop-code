"""Spec sections: `init` Command, `init` Catalog File, `catalog.json` Root Schema."""

import json

from conftest import read_catalog

URL = "http://example.invalid/media.json"


# Spec: Syntax | `python mvault.py init <name> <url>`; Vault directory | `<name>/`
def test_init_creates_vault_directory(run, tmp_path):
    assert run("init", "vault", URL).returncode == 0
    assert (tmp_path / "vault").is_dir()


# Spec: Catalog path | `<name>/catalog.json`
def test_init_creates_catalog_at_expected_path(run, tmp_path):
    run("init", "vault", URL)
    assert (tmp_path / "vault" / "catalog.json").is_file()


# Spec: Success effect | Create new vault with empty catalog
def test_init_catalog_matches_required_layout(run, tmp_path):
    run("init", "vault", URL)
    assert read_catalog(tmp_path / "vault") == {
        "version": 3,
        "source": URL,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


# Spec: `version` | integer | `3`
def test_version_is_integer_three(run, tmp_path):
    run("init", "vault", URL)
    version = read_catalog(tmp_path / "vault")["version"]
    assert version == 3 and isinstance(version, int) and not isinstance(version, bool)


# Spec: `source` | string | Source URL passed to `init`
def test_source_is_the_url_passed_to_init(run, tmp_path):
    other = "https://cdn.example.test/a/b/c.json?token=xyz"
    run("init", "vault", other)
    assert read_catalog(tmp_path / "vault")["source"] == other


# Spec: `episodes`/`streams`/`clips` | array | Entry objects for ... content
def test_categories_start_as_empty_arrays(run, tmp_path):
    run("init", "vault", URL)
    catalog = read_catalog(tmp_path / "vault")
    for category in ("episodes", "streams", "clips"):
        assert catalog[category] == []


# Spec: New vaults must start with the exact category layout below.
def test_catalog_has_no_extra_root_fields(run, tmp_path):
    run("init", "vault", URL)
    assert set(read_catalog(tmp_path / "vault")) == {
        "version",
        "source",
        "episodes",
        "streams",
        "clips",
    }


# Spec: Existing directory | Error to stderr including `<name>`; exit non-zero
def test_init_over_existing_directory_errors(run, tmp_path):
    (tmp_path / "vault").mkdir()
    result = run("init", "vault", URL)
    assert result.returncode != 0
    assert "vault" in result.stderr
    assert result.stdout == ""


# Spec: Existing directory | ... no modification of existing data
def test_init_over_existing_directory_preserves_data(run, tmp_path):
    existing = tmp_path / "vault"
    existing.mkdir()
    (existing / "catalog.json").write_text('{"version": 3, "keep": "me"}')
    (existing / "notes.txt").write_text("hand written")

    run("init", "vault", URL)

    assert json.loads((existing / "catalog.json").read_text()) == {
        "version": 3,
        "keep": "me",
    }
    assert (existing / "notes.txt").read_text() == "hand written"


# Spec: Existing directory ... no modification of existing data (T14: any existing path)
def test_init_over_existing_file_errors_without_clobbering(run, tmp_path):
    (tmp_path / "vault").write_text("not a vault")
    result = run("init", "vault", URL)
    assert result.returncode != 0
    assert "vault" in result.stderr
    assert (tmp_path / "vault").read_text() == "not a vault"


# Spec: Syntax | `python mvault.py init <name> <url>` (both operands required)
def test_init_requires_name_and_url(run):
    assert run("init").returncode != 0
    assert run("init", "vault").returncode != 0


# Spec: Vault directory | `<name>/` (nested names are created under the given path)
def test_init_accepts_nested_vault_path(run, tmp_path):
    (tmp_path / "parent").mkdir()
    assert run("init", "parent/vault", URL).returncode == 0
    assert (tmp_path / "parent" / "vault" / "catalog.json").is_file()
