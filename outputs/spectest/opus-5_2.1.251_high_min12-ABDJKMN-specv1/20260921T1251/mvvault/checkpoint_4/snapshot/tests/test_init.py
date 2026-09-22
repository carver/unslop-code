"""Spec sections: `init` Command / `init` Catalog File / `catalog.json` Root Schema."""

from __future__ import annotations

import json
from pathlib import Path

URL = "http://example.invalid/feed.json"


# Spec: | Syntax | `python mvault.py init <name> <url>` |
#       | Vault directory | `<name>/` |
def test_init_creates_vault_directory(run_cli, workdir):
    result = run_cli("init", "myvault", URL)
    assert result.returncode == 0, result.stderr
    assert (Path(workdir) / "myvault").is_dir()


# Spec: | Catalog path | `<name>/catalog.json` |
def test_init_creates_catalog_at_expected_path(run_cli, workdir):
    assert run_cli("init", "myvault", URL).returncode == 0
    assert (Path(workdir) / "myvault" / "catalog.json").is_file()


# Spec: | Success effect | Create new vault with empty catalog |
# Context: "New vaults must start with the exact category layout below."
def test_init_catalog_is_exact_layout(run_cli, workdir):
    assert run_cli("init", "myvault", URL).returncode == 0
    data = json.loads((Path(workdir) / "myvault" / "catalog.json").read_text(encoding="utf-8"))
    assert data == {
        "version": 3,
        "source": URL,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


# Spec: Root schema | `version` | integer | `3` |
def test_root_version_is_integer_three(run_cli, workdir):
    assert run_cli("init", "myvault", URL).returncode == 0
    data = json.loads((Path(workdir) / "myvault" / "catalog.json").read_text(encoding="utf-8"))
    assert data["version"] == 3
    assert isinstance(data["version"], int) and not isinstance(data["version"], bool)


# Spec: Root schema | `source` | string | Source URL passed to `init` |
def test_root_source_is_url_passed_to_init(run_cli, workdir):
    url = "https://media.example.com/api/v1/catalog?x=1"
    assert run_cli("init", "myvault", url).returncode == 0
    data = json.loads((Path(workdir) / "myvault" / "catalog.json").read_text(encoding="utf-8"))
    assert data["source"] == url
    assert isinstance(data["source"], str)


# Spec: Root schema | `episodes` / `streams` / `clips` | array | Entry objects for ... content |
def test_root_categories_are_arrays(run_cli, workdir):
    assert run_cli("init", "myvault", URL).returncode == 0
    data = json.loads((Path(workdir) / "myvault" / "catalog.json").read_text(encoding="utf-8"))
    for category in ("episodes", "streams", "clips"):
        assert isinstance(data[category], list)
        assert data[category] == []


# Spec: | Existing directory | Error to stderr including `<name>`; exit non-zero; ... |
def test_init_existing_directory_exits_non_zero(run_cli, workdir):
    (Path(workdir) / "myvault").mkdir()
    result = run_cli("init", "myvault", URL)
    assert result.returncode != 0


# Spec: | Existing directory | Error to stderr including `<name>` ... |
def test_init_existing_directory_error_names_vault_on_stderr(run_cli, workdir):
    (Path(workdir) / "myvault").mkdir()
    result = run_cli("init", "myvault", URL)
    assert "myvault" in result.stderr
    assert result.stdout == ""


# Spec: | Existing directory | ... no modification of existing data |
def test_init_existing_directory_does_not_modify_data(run_cli, workdir, snapshot):
    target = Path(workdir) / "myvault"
    target.mkdir()
    (target / "catalog.json").write_text('{"version": 3, "source": "old", '
                                         '"episodes": [], "streams": [], "clips": []}',
                                         encoding="utf-8")
    (target / "notes.txt").write_text("keep me", encoding="utf-8")
    before = snapshot(target)

    assert run_cli("init", "myvault", URL).returncode != 0
    assert snapshot(target) == before


# Spec: | Existing directory | ... (an existing vault dir that was itself created by init)
def test_init_twice_is_an_error(run_cli, workdir, snapshot):
    assert run_cli("init", "myvault", URL).returncode == 0
    before = snapshot(Path(workdir) / "myvault")
    result = run_cli("init", "myvault", "http://other.invalid/f.json")
    assert result.returncode != 0
    assert "myvault" in result.stderr
    assert snapshot(Path(workdir) / "myvault") == before


# Spec: | Syntax | `python mvault.py init <name> <url>` | (arity is part of the syntax)
def test_init_requires_name_and_url(run_cli):
    assert run_cli("init").returncode != 0
    assert run_cli("init", "onlyname").returncode != 0
