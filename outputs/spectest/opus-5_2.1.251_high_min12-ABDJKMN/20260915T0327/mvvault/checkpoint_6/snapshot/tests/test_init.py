"""Spec sections: `init` Command / `init` Catalog File / root schema."""
import json
import os

import pytest

from conftest import read_catalog

URL = "https://example.invalid/feed.json"


# --- Phrase: "Syntax | `python mvault.py init <name> <url>`" +
#     "Success effect | Create new vault with empty catalog"
def test_init_exits_zero(run):
    result = run("init", "vault", URL)
    assert result.returncode == 0, result


# --- Phrase: "Vault directory | `<name>/`"
def test_init_creates_vault_directory(run, tmp_path):
    run("init", "vault", URL)
    assert (tmp_path / "vault").is_dir()


# --- Phrase: "Catalog path | `<name>/catalog.json`"
def test_init_creates_catalog_at_expected_path(run, tmp_path):
    run("init", "vault", URL)
    assert (tmp_path / "vault" / "catalog.json").is_file()


# --- Phrase: "New vaults must start with the exact category layout below."
#     (context: the four-key JSON document shown in `init` Catalog File)
def test_init_catalog_exact_layout(run, tmp_path):
    run("init", "vault", URL)
    assert read_catalog(tmp_path) == {
        "version": 3,
        "source": URL,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


# --- Phrase: "| `version` | integer | `3` |"
def test_catalog_version_is_integer_three(run, tmp_path):
    run("init", "vault", URL)
    catalog = read_catalog(tmp_path)
    assert catalog["version"] == 3
    assert isinstance(catalog["version"], int)
    assert not isinstance(catalog["version"], bool)


# --- Phrase: "| `source` | string | Source URL passed to `init` |"
@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/feed.json",
        "http://127.0.0.1:8080/a?b=c&d=e",
        "https://example.invalid/unicode/%C3%A9",
    ],
)
def test_catalog_source_is_the_url_passed_to_init(run, tmp_path, url):
    run("init", "vault", url)
    catalog = read_catalog(tmp_path)
    assert catalog["source"] == url
    assert isinstance(catalog["source"], str)


# --- Phrase: "| `episodes` | array |", "| `streams` | array |",
#     "| `clips` | array |" (context: empty catalog on init)
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_catalog_categories_are_empty_arrays(run, tmp_path, category):
    run("init", "vault", URL)
    catalog = read_catalog(tmp_path)
    assert catalog[category] == []
    assert isinstance(catalog[category], list)


# --- Phrase: "Existing directory | Error to stderr including `<name>`;
#     exit non-zero; no modification of existing data"
def test_init_existing_vault_exits_non_zero(run, tmp_path):
    run("init", "vault", URL)
    result = run("init", "vault", "https://example.invalid/other.json")
    assert result.returncode != 0, result


def test_init_existing_vault_error_mentions_name_on_stderr(run, tmp_path):
    run("init", "myvault", URL)
    result = run("init", "myvault", "https://example.invalid/other.json")
    assert "myvault" in result.stderr, result
    assert result.stderr.strip(), result


def test_init_existing_vault_leaves_catalog_unmodified(run, tmp_path):
    run("init", "vault", URL)
    before = (tmp_path / "vault" / "catalog.json").read_bytes()
    run("init", "vault", "https://example.invalid/other.json")
    assert (tmp_path / "vault" / "catalog.json").read_bytes() == before


def test_init_existing_directory_that_is_not_a_vault_is_an_error(run, tmp_path):
    target = tmp_path / "vault"
    target.mkdir()
    (target / "keepme.txt").write_text("data")
    result = run("init", "vault", URL)
    assert result.returncode != 0, result
    assert "vault" in result.stderr, result
    assert (target / "keepme.txt").read_text() == "data"
    assert not (target / "catalog.json").exists()


# --- Phrase: "Vault directory | `<name>/`" (context: a nested/relative name
#     still resolves relative to the working directory)
def test_init_accepts_nested_relative_name(run, tmp_path):
    (tmp_path / "parent").mkdir()
    result = run("init", os.path.join("parent", "vault"), URL)
    assert result.returncode == 0, result
    with open(str(tmp_path / "parent" / "vault" / "catalog.json")) as fh:
        assert json.load(fh)["source"] == URL
