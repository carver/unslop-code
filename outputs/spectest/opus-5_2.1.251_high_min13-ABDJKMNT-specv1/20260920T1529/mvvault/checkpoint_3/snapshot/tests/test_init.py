"""Spec sections: `init` Command / `init` Catalog File / `catalog.json` Root Schema."""

import json

from conftest import read_catalog, run_cli

URL = "http://example.invalid/feed.json"


# `init` Command: "Syntax | `python mvault.py init <name> <url>`" with
# "Vault directory | `<name>/`".
def test_init_creates_vault_directory(tmp_path):
    run_cli("init", "demo", URL, cwd=tmp_path)
    assert (tmp_path / "demo").is_dir()


# `init` Command: "Catalog path | `<name>/catalog.json`".
def test_init_creates_catalog_at_documented_path(tmp_path):
    run_cli("init", "demo", URL, cwd=tmp_path)
    assert (tmp_path / "demo" / "catalog.json").is_file()


# `init` Command: "Success effect | Create new vault with empty catalog" —
# a successful init exits zero.
def test_init_exits_zero(tmp_path):
    assert run_cli("init", "demo", URL, cwd=tmp_path).returncode == 0


# `init` Catalog File: "New vaults must start with the exact category layout
# below." — the whole document, compared as parsed JSON.
def test_init_catalog_matches_documented_layout(tmp_path):
    run_cli("init", "demo", URL, cwd=tmp_path)
    assert read_catalog(tmp_path / "demo") == {
        "version": 3,
        "source": URL,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


# Root Schema: "`version` | integer | `3`".
def test_catalog_version_is_integer_three(tmp_path):
    run_cli("init", "demo", URL, cwd=tmp_path)
    version = read_catalog(tmp_path / "demo")["version"]
    assert version == 3 and isinstance(version, int)


# Root Schema: "`source` | string | Source URL passed to `init`".
def test_catalog_source_is_the_url_passed_to_init(tmp_path):
    run_cli("init", "demo", "https://example.invalid/other.json", cwd=tmp_path)
    assert read_catalog(tmp_path / "demo")["source"] == "https://example.invalid/other.json"


# Root Schema: "`episodes` / `streams` / `clips` | array" — empty on a new vault.
def test_catalog_categories_start_as_empty_arrays(tmp_path):
    run_cli("init", "demo", URL, cwd=tmp_path)
    catalog = read_catalog(tmp_path / "demo")
    assert catalog["episodes"] == [] and catalog["streams"] == [] and catalog["clips"] == []


# `init` Command: "Vault directory | `<name>/`" — a nested relative name works.
def test_init_accepts_a_nested_name(tmp_path):
    (tmp_path / "parent").mkdir()
    result = run_cli("init", "parent/demo", URL, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "parent" / "demo" / "catalog.json").is_file()


# `init` Command: "Existing directory | Error to stderr including `<name>`".
def test_init_on_existing_directory_names_the_vault_on_stderr(tmp_path):
    (tmp_path / "demo").mkdir()
    result = run_cli("init", "demo", URL, cwd=tmp_path)
    assert "demo" in result.stderr


# `init` Command: "Existing directory | ... exit non-zero".
def test_init_on_existing_directory_exits_non_zero(tmp_path):
    (tmp_path / "demo").mkdir()
    assert run_cli("init", "demo", URL, cwd=tmp_path).returncode != 0


# `init` Command: "Existing directory | ... no modification of existing data".
def test_init_on_existing_directory_leaves_data_untouched(tmp_path):
    vault = tmp_path / "demo"
    vault.mkdir()
    (vault / "catalog.json").write_text(json.dumps({"version": 3, "keep": "me"}))
    (vault / "other.txt").write_text("untouched")

    run_cli("init", "demo", URL, cwd=tmp_path)

    assert json.loads((vault / "catalog.json").read_text()) == {"version": 3, "keep": "me"}
    assert (vault / "other.txt").read_text() == "untouched"


# `init` Command: "Existing directory" — an existing vault created by init is
# itself an existing directory.
def test_init_twice_fails_the_second_time(tmp_path):
    run_cli("init", "demo", URL, cwd=tmp_path)
    result = run_cli("init", "demo", "http://example.invalid/changed.json", cwd=tmp_path)
    assert result.returncode != 0
    assert read_catalog(tmp_path / "demo")["source"] == URL
