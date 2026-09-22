"""Spec: `init` Command, `init` Catalog File, `catalog.json` Root Schema."""
import json
import os

from conftest import read_catalog, read_json

URL = "http://example.invalid/source.json"


# Spec: "| Syntax | `python mvault.py init <name> <url>` |" +
# "| Vault directory | `<name>/` |"
def test_init_creates_vault_directory(run, tmp_path):
    res = run("init", "myvault", URL)
    assert res.returncode == 0, res
    assert (tmp_path / "myvault").is_dir()


# Spec: "| Catalog path | `<name>/catalog.json` |"
def test_init_creates_catalog_at_expected_path(run, tmp_path):
    run("init", "myvault", URL)
    assert (tmp_path / "myvault" / "catalog.json").is_file()


# Spec: "| Success effect | Create new vault with empty catalog |" plus the
# exact `init` Catalog File layout.
def test_init_catalog_exact_layout(run, tmp_path):
    run("init", "myvault", URL)
    catalog = read_json(str(tmp_path / "myvault" / "catalog.json"))
    assert catalog == {
        "version": 3,
        "source": URL,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


# Spec: "New vaults must start with the exact category layout below." --
# no extra root keys beyond the five documented ones.
def test_init_catalog_has_no_extra_root_keys(run, tmp_path):
    run("init", "myvault", URL)
    catalog = read_json(str(tmp_path / "myvault" / "catalog.json"))
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Spec: Root Schema "| `version` | integer | `3` |"
def test_root_version_is_integer_three(run, tmp_path):
    run("init", "v", URL)
    catalog = read_catalog(tmp_path, "v")
    assert catalog["version"] == 3
    assert isinstance(catalog["version"], int)
    assert not isinstance(catalog["version"], bool)


# Spec: Root Schema "| `source` | string | Source URL passed to `init` |"
def test_root_source_is_the_url_passed_to_init(run, tmp_path):
    run("init", "v", "https://example.test/feed?x=1&y=2")
    catalog = read_catalog(tmp_path, "v")
    assert catalog["source"] == "https://example.test/feed?x=1&y=2"
    assert isinstance(catalog["source"], str)


# Spec: Root Schema rows for `episodes` / `streams` / `clips` -- "array".
def test_root_categories_are_arrays(run, tmp_path):
    run("init", "v", URL)
    catalog = read_catalog(tmp_path, "v")
    for category in ("episodes", "streams", "clips"):
        assert isinstance(catalog[category], list)


# Spec: "| Success effect | Create new vault with empty catalog |"
def test_init_catalog_is_empty(run, tmp_path):
    run("init", "v", URL)
    catalog = read_catalog(tmp_path, "v")
    assert catalog["episodes"] == []
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# Spec: init writes nothing else -- there is no pre-existing catalog, so the
# backup trigger ("Before every write to existing `catalog.json`") is not hit.
def test_init_does_not_create_backup(run, tmp_path):
    run("init", "v", URL)
    assert not (tmp_path / "v" / "catalog.bak").exists()


# Spec: "| Existing directory | Error to stderr including `<name>`; exit
# non-zero; no modification of existing data |" -- exit code.
def test_init_existing_directory_exit_non_zero(run, tmp_path):
    (tmp_path / "taken").mkdir()
    assert run("init", "taken", URL).returncode != 0


# Spec: "Existing directory | Error to stderr including `<name>`"
def test_init_existing_directory_error_mentions_name_on_stderr(run, tmp_path):
    (tmp_path / "taken").mkdir()
    res = run("init", "taken", URL)
    assert "taken" in res.stderr
    assert res.stdout == ""


# Spec: "... no modification of existing data"
def test_init_existing_directory_leaves_data_untouched(run, tmp_path):
    victim = tmp_path / "taken"
    victim.mkdir()
    (victim / "catalog.json").write_text('{"version": 3, "keep": "me"}')
    (victim / "other.txt").write_text("precious")

    run("init", "taken", "http://example.invalid/other.json")

    assert json.loads((victim / "catalog.json").read_text()) == {
        "version": 3,
        "keep": "me",
    }
    assert (victim / "other.txt").read_text() == "precious"


# Spec: "Existing directory" -- an already-initialised vault must not be reset.
def test_init_twice_does_not_reinitialise(run, tmp_path):
    run("init", "v", URL)
    first = read_catalog(tmp_path, "v")
    res = run("init", "v", "http://example.invalid/changed.json")
    assert res.returncode != 0
    assert read_catalog(tmp_path, "v") == first


# Spec: "`init` with existing vault directory | stderr | non-zero | Message
# includes vault name" (Error Handling table).
def test_init_error_handling_row(run, tmp_path):
    (tmp_path / "dup").mkdir()
    res = run("init", "dup", URL)
    assert res.returncode != 0
    assert "dup" in res.stderr


# Spec: "Syntax | `python mvault.py init <name> <url>`" -- both operands are
# required; a malformed invocation is a usage error on stderr.
def test_init_requires_name_and_url(run, tmp_path):
    res = run("init", "onlyname")
    assert res.returncode != 0
    assert res.stderr != ""
    assert not (tmp_path / "onlyname").exists()
