"""Spec: `digest` Command -- syntax, input, streams, read-only guarantee."""
import os

import pytest

from conftest import catalog_path, backup_path, catalog_bytes
from digest_helpers import (K1, K2, v1, v2, v3, v3_entry, legacy_entry, v1_entry,
                            trailing_line)


# Spec: "| Syntax | `python mvault.py digest <name>` |"
def test_digest_syntax(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    assert run("digest", "vault").returncode == 0


# Spec: "| Input | Existing vault of any supported version |" -- v3.
def test_digest_accepts_v3(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    assert run("digest", "vault").returncode == 0


# Spec: "| Input | Existing vault of any supported version |" -- v2.
def test_digest_accepts_v2(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    assert run("digest", "vault").returncode == 0


# Spec: "| Input | Existing vault of any supported version |" -- v1.
def test_digest_accepts_v1(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    assert run("digest", "vault").returncode == 0


# Spec: "The `digest` command works on vaults of any supported version without
# requiring prior migration."
def test_digest_requires_no_prior_migration(run, make_vault, tmp_path):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    before = catalog_bytes(tmp_path)
    assert run("digest", "vault").returncode == 0
    assert catalog_bytes(tmp_path) == before


# Spec: "| Output stream | stdout |"
def test_digest_writes_to_stdout(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    res = run("digest", "vault")
    assert res.stdout.strip() != ""
    assert res.stderr == ""


# Spec: "| Purpose | Human-readable summary of notable changes derived from
# tracked-field history |"
def test_digest_summarises_tracked_field_history(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "Old", K2: "New"})]))
    out = run("digest", "vault").stdout
    assert "New" in out


# Spec: "| Catalog modification | `digest` is read-only; it never writes
# `catalog.json` or `catalog.bak` |" -- v2 vault, no migration written.
def test_digest_never_writes_catalog(run, make_vault, tmp_path):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    before = catalog_bytes(tmp_path)
    run("digest", "vault")
    assert catalog_bytes(tmp_path) == before


# Spec: "it never writes ... `catalog.bak`"
def test_digest_creates_no_backup(run, make_vault, tmp_path):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    run("digest", "vault")
    assert not os.path.exists(backup_path(tmp_path))


# Spec: "digest is read-only" -- nothing new appears in the vault directory.
def test_digest_adds_no_files_to_the_vault(run, make_vault, tmp_path):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    before = sorted(os.listdir(str(tmp_path / "vault")))
    run("digest", "vault")
    assert sorted(os.listdir(str(tmp_path / "vault"))) == before


# Spec: "| Missing vault | Error to stderr including vault name; exit
# non-zero |"
def test_digest_missing_vault_errors(run, tmp_path):
    res = run("digest", "ghostvault")
    assert res.returncode != 0
    assert "ghostvault" in res.stderr
    assert res.stdout == ""


# Spec: "| Missing vault for `digest` | stderr | non-zero | Message includes
# vault name |" -- also when the directory exists but the catalog does not.
def test_digest_vault_without_catalog_errors(run, tmp_path):
    (tmp_path / "hollow").mkdir()
    res = run("digest", "hollow")
    assert res.returncode != 0
    assert "hollow" in res.stderr


# Spec: "| `digest` on vault with unsupported version | stderr | non-zero |
# Message includes version value |"
@pytest.mark.parametrize("version", [4, 7, 99])
def test_digest_unsupported_version_reports_version(run, make_vault, version):
    catalog = v3()
    catalog["version"] = version
    make_vault(catalog)
    res = run("digest", "vault")
    assert res.returncode != 0
    assert str(version) in res.stderr
    assert res.stdout == ""


# Spec: "digest on vault with unsupported version ... Message includes version
# value" -- and nothing is written.
def test_digest_unsupported_version_writes_nothing(run, make_vault, tmp_path):
    catalog = v3()
    catalog["version"] = 9
    make_vault(catalog)
    before = catalog_bytes(tmp_path)
    run("digest", "vault")
    assert catalog_bytes(tmp_path) == before
    assert not os.path.exists(backup_path(tmp_path))


# Spec: "| Trailing line | Metadata about the digest run |" -- there is always
# a trailing line, even when nothing changed.
def test_trailing_line_always_present(run, make_vault):
    make_vault(v3())
    out = run("digest", "vault").stdout
    assert trailing_line(out).strip() != ""


# Spec: "| Trailing line | Metadata about the digest run |" -- it mentions the
# vault the digest ran on.
def test_trailing_line_names_the_vault(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]), name="myvault")
    out = run("digest", "myvault").stdout
    assert "myvault" in trailing_line(out)
