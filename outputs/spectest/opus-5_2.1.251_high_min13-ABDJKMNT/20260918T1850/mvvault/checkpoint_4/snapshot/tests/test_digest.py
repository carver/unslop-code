"""Spec sections: `digest` Command, `digest` Change Classification, `digest` Group
Precedence, Error Handling (`digest`)."""

from conftest import (
    V2_LATER,
    V2_STAMP,
    v1_catalog,
    v1_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

LATEST = "2024-06-17T09:40:00"


def updated_entry(entry_id, **changes):
    """A v3 entry whose named tracked fields gained a differing second value."""
    histories = {field: {V2_STAMP: before, V2_LATER: after} for field, (before, after) in changes.items()}
    return v3_entry(entry_id, **histories)


# Spec: Syntax | `python mvault.py digest <name>`; Output stream | stdout
def test_digest_writes_to_stdout(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    result = run("digest", "vault")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert result.stderr == ""


# Spec: Missing vault | Error to stderr including vault name; exit non-zero
def test_digest_missing_vault_names_the_vault(run, tmp_path):
    result = run("digest", "nowhere")
    assert result.returncode != 0
    assert "nowhere" in result.stderr
    assert result.stdout == ""


# Spec: Missing vault | ... a directory without a catalog is also missing
def test_digest_directory_without_catalog_errors(run, tmp_path):
    (tmp_path / "hollow").mkdir()
    result = run("digest", "hollow")
    assert result.returncode != 0
    assert "hollow" in result.stderr


# Spec: Catalog modification | `digest` is read-only; it never writes `catalog.json`
def test_digest_does_not_modify_the_catalog(run, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    before = (vault / "catalog.json").read_bytes()
    assert run("digest", "vault").returncode == 0
    assert (vault / "catalog.json").read_bytes() == before


# Spec: Catalog modification | ... it never writes `catalog.bak`
def test_digest_writes_no_backup(run, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    run("digest", "vault")
    assert not (vault / "catalog.bak").exists()


# Spec: `digest` on vault with unsupported version | stderr | non-zero | includes version
def test_digest_unsupported_version_reports_the_value(run, tmp_path):
    write_vault(tmp_path, {"version": 4, "source": "http://x.invalid/s.json", "episodes": []})
    result = run("digest", "vault")
    assert result.returncode != 0
    assert "4" in result.stderr


# Spec: `digest` on vault with unsupported version | ... a non-integer version too
def test_digest_non_integer_version_reports_the_value(run, tmp_path):
    write_vault(tmp_path, {"version": "three", "source": "http://x.invalid/s.json"})
    result = run("digest", "vault")
    assert result.returncode != 0
    assert "three" in result.stderr


# Spec: Additions | Entry has only initial observations; no tracked field has a second entry
def test_entry_with_only_initial_observations_is_an_addition(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    stdout = run("digest", "vault").stdout
    assert "Added" in stdout
    assert "Title e1" in stdout


# Spec: Field updates | At least one tracked field has two or more history entries and
# the latest two values differ
def test_entry_with_a_changed_field_is_an_update(run, tmp_path):
    entry = updated_entry("e1", views=(10, 99))
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Updated" in stdout
    assert "Added" not in stdout
    assert "(views)" in stdout


# Spec: Field updates | ... the latest two values differ (equal values do not qualify)
def test_repeated_identical_value_is_not_an_update(run, tmp_path):
    entry = v3_entry("e1", views={V2_STAMP: 10, V2_LATER: 10})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Updated" not in stdout
    assert "Added" not in stdout
    assert "Title e1" not in stdout


# Spec: No notable changes anywhere | Indicate that no notable changes were found
def test_empty_catalog_reports_no_notable_changes(run, tmp_path):
    write_vault(tmp_path, v3_catalog())
    stdout = run("digest", "vault").stdout
    assert "no notable changes" in stdout.lower()


# Spec: Removals | Latest `removed` value is `true` and prior `removed` value,
# if present, is `false`
def test_removed_entry_is_a_removal(run, tmp_path):
    entry = v3_entry("e1", removed={V2_STAMP: False, V2_LATER: True})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Removed" in stdout
    assert "Title e1" in stdout


# Spec: Removals | ... prior `removed` value, *if present* (a lone `true` still qualifies)
def test_removal_without_a_prior_value_qualifies(run, tmp_path):
    entry = v3_entry("e1", removed={V2_STAMP: True})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    assert "Removed" in run("digest", "vault").stdout


# Spec: Removals | ... an entry that is not currently removed is not a removal
def test_reappeared_entry_is_not_a_removal(run, tmp_path):
    entry = v3_entry("e1", removed={V2_STAMP: False, V2_LATER: True, LATEST: False})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Removed:" not in stdout
    assert "Title e1" in stdout


# Spec: Group Precedence | Each entry may appear once; Removals outrank additions/updates
def test_removal_outranks_a_field_update(run, tmp_path):
    entry = v3_entry(
        "e1",
        title={V2_STAMP: "Old", V2_LATER: "New"},
        removed={V2_STAMP: False, V2_LATER: True},
    )
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert stdout.count("New") == 1
    assert "Removed" in stdout
    assert "Updated" not in stdout


# Spec: Group Precedence | Additions outrank field updates
def test_addition_outranks_field_updates(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    stdout = run("digest", "vault").stdout
    assert stdout.count("Title e1") == 1
    assert "Updated" not in stdout


# Spec: Group Precedence | Each entry may appear once
def test_each_entry_appears_once(run, tmp_path):
    entries = [
        v3_entry("e1"),
        updated_entry("e2", title=("Old e2", "New e2")),
        v3_entry("e3", removed={V2_STAMP: False, V2_LATER: True}),
    ]
    write_vault(tmp_path, v3_catalog(episodes=entries))
    stdout = run("digest", "vault").stdout
    assert stdout.count("Title e1") == 1
    assert stdout.count("New e2") == 1
    assert stdout.count("Title e3") == 1
