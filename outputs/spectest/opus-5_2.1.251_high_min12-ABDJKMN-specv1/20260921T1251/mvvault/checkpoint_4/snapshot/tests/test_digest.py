"""Spec sections: `digest` Command, `digest` Format-Aware Loading, `digest`
Change Classification, `digest` Group Precedence, `digest` Current Value
Resolution, and `digest` Source URL Resolution."""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# | Syntax | `python mvault.py digest <name>` |
# | Input | Existing vault of any supported version |
# | Output stream | stdout |
# ---------------------------------------------------------------------------

# Spec: | Syntax | `python mvault.py digest <name>` |
def test_digest_runs_on_a_v3_vault(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    result = run_cli("digest", "vault")
    assert result.returncode == 0, result.stderr


# Spec: | Output stream | stdout |
def test_digest_writes_to_stdout(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    result = run_cli("digest", "vault")
    assert result.stdout.strip() != ""


# Spec: | Purpose | Human-readable summary of notable changes derived from
#   tracked-field history |
def test_digest_summarizes_tracked_field_history(run_cli, make_vault, catalogs):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "Old", catalogs.STAMP_2: "New"}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert "New" in result.stdout


# Spec: "The `digest` command works on vaults of any supported version without
#   requiring prior migration."
def test_digest_runs_on_a_v1_vault(run_cli, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    result = run_cli("digest", "vault")
    assert result.returncode == 0, result.stderr


# Spec: | Input | Existing vault of any supported version |
def test_digest_runs_on_a_v2_vault(run_cli, make_vault, legacy):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    result = run_cli("digest", "vault")
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# | Catalog modification | `digest` is read-only; it never writes
#   `catalog.json` or `catalog.bak` |
# ---------------------------------------------------------------------------

# Spec: | Catalog modification | `digest` is read-only ... |
def test_digest_leaves_the_vault_byte_identical(
    run_cli, make_vault, catalogs, snapshot
):
    vault_dir = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    before = snapshot(vault_dir)
    assert run_cli("digest", "vault").returncode == 0
    assert snapshot(vault_dir) == before


# Spec: | Catalog modification | ... it never writes ... `catalog.bak` |
def test_digest_writes_no_backup(run_cli, make_vault, catalogs):
    vault_dir = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    assert run_cli("digest", "vault").returncode == 0
    assert not (Path(vault_dir) / "catalog.bak").exists()


# Spec: "`digest` must work directly on v1, v2, and v3 catalogs without
#   migrating."
def test_digest_does_not_migrate_a_v1_catalog(
    run_cli, make_vault, legacy, workdir, helpers
):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("digest", "vault").returncode == 0
    assert helpers.read_catalog(workdir)["version"] == 1


# Spec: "`digest` must work directly on v1, v2, and v3 catalogs without
#   migrating."
def test_digest_does_not_migrate_a_v2_catalog(
    run_cli, make_vault, legacy, workdir, helpers
):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    assert run_cli("digest", "vault").returncode == 0
    assert helpers.read_catalog(workdir)["version"] == 2


# ---------------------------------------------------------------------------
# | Missing vault | Error to stderr including vault name; exit non-zero |
# ---------------------------------------------------------------------------

# Spec: | Missing vault | Error to stderr including vault name; exit non-zero |
def test_missing_vault_exits_non_zero(run_cli, workdir):
    result = run_cli("digest", "nosuchvault")
    assert result.returncode != 0


# Spec: | Missing vault | Error to stderr including vault name; ... |
def test_missing_vault_names_the_vault_on_stderr(run_cli, workdir):
    result = run_cli("digest", "nosuchvault")
    assert "nosuchvault" in result.stderr


# Spec: | Missing vault | ... |
# Context: a directory without a catalog is not a usable vault either.
def test_vault_without_catalog_is_an_error(run_cli, workdir):
    (Path(workdir) / "empty").mkdir()
    result = run_cli("digest", "empty")
    assert result.returncode != 0
    assert "empty" in result.stderr


# ---------------------------------------------------------------------------
# | `digest` on vault with unsupported version | stderr | non-zero | Message
#   includes version value |
# ---------------------------------------------------------------------------

# Spec: | `digest` on vault with unsupported version | stderr | non-zero | ... |
def test_unsupported_version_exits_non_zero(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(version=99))
    result = run_cli("digest", "vault")
    assert result.returncode != 0


# Spec: | ... | Message includes version value |
def test_unsupported_version_message_includes_the_version(
    run_cli, make_vault, catalogs
):
    make_vault(catalogs.catalog(version=99))
    result = run_cli("digest", "vault")
    assert "99" in result.stderr


# Spec: | ... | Message includes version value |
# Context: a non-integer version is equally unsupported.
def test_unsupported_non_integer_version_is_reported(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(version="3"))
    result = run_cli("digest", "vault")
    assert result.returncode != 0
    assert "3" in result.stderr


# ---------------------------------------------------------------------------
# | Additions | Entry has only initial observations; no tracked field has a
#   second history entry |
# ---------------------------------------------------------------------------

# Spec: | Additions | Entry has only initial observations ... |
def test_entry_with_only_initial_observations_is_an_addition(
    run_cli, make_vault, catalogs, digest
):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    result = run_cli("digest", "vault")
    assert any("Title e1" in line
               for line in digest.group(result.stdout, "Episodes", "Additions"))


# Spec: | Additions | ... no tracked field has a second history entry |
def test_entry_with_a_second_history_entry_is_not_an_addition(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 100, catalogs.STAMP_2: 200}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert digest.group(result.stdout, "Episodes", "Additions") == []


# ---------------------------------------------------------------------------
# | Removals | Latest `removed` value is `true` and prior `removed` value, if
#   present, is `false` |
# ---------------------------------------------------------------------------

# Spec: | Removals | Latest `removed` value is `true` and prior `removed`
#   value, if present, is `false` |
def test_removed_entry_is_a_removal(run_cli, make_vault, catalogs, digest):
    entry = catalogs.entry("e1")
    entry["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert any("Title e1" in line
               for line in digest.group(result.stdout, "Episodes", "Removals"))


# Spec: | Removals | Latest `removed` value is `true` and prior ... , if
#   present, is `false` |
# Context: "if present" - a history whose only value is `true` still qualifies.
def test_removal_without_a_prior_value_qualifies(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["removed"] = {catalogs.STAMP_1: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert any("Title e1" in line
               for line in digest.group(result.stdout, "Episodes", "Removals"))


# Spec: | Removals | ... and prior `removed` value, if present, is `false` |
# Context: an entry already removed before the latest observation does not
# re-qualify as a removal.
def test_already_removed_entry_is_not_a_removal(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["removed"] = {
        catalogs.STAMP_1: False, catalogs.STAMP_2: True, catalogs.STAMP_3: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert digest.group(result.stdout, "Episodes", "Removals") == []


# Spec: | Removals | ... | (latest `removed` is `false` -> not a removal)
def test_present_entry_is_not_a_removal(run_cli, make_vault, catalogs, digest):
    entry = catalogs.entry("e1")
    entry["removed"] = {catalogs.STAMP_1: True, catalogs.STAMP_2: False}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert digest.group(result.stdout, "Episodes", "Removals") == []


# ---------------------------------------------------------------------------
# | Field updates | At least one tracked field has two or more history entries
#   and the latest two values differ |
# ---------------------------------------------------------------------------

# Spec: | Field updates | At least one tracked field has two or more history
#   entries and the latest two values differ |
def test_changed_field_makes_a_field_update(run_cli, make_vault, catalogs, digest):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "Old", catalogs.STAMP_2: "New"}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    lines = digest.group(result.stdout, "Episodes", "Field updates")
    assert any("New" in line for line in lines), result.stdout


# Spec: | Field updates | ... and the latest two values differ |
# Context: two history entries holding the same value are not an update.
def test_repeated_identical_value_is_not_a_field_update(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "Same", catalogs.STAMP_2: "Same"}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert digest.group(result.stdout, "Episodes", "Field updates") == []


# Spec: | Field updates | ... the latest two values differ |
# Context: only the latest two values matter, not older ones.
def test_only_the_latest_two_values_decide_a_field_update(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["views"] = {
        catalogs.STAMP_1: 1, catalogs.STAMP_2: 5, catalogs.STAMP_3: 5}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert digest.group(result.stdout, "Episodes", "Field updates") == []


# Spec: | Field updates | Same rule applied to available tracked fields |
# Context: v2 has no `removed` field; the source-tracked fields still qualify.
def test_v2_field_update_uses_available_fields(
    run_cli, make_vault, legacy, digest
):
    entry = legacy.v2_entry("e1")
    entry["views"] = {"2024-06-15T09:40:00": 10, "2024-06-16T09:40:00": 20}
    make_vault(legacy.v2_catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    lines = digest.group(result.stdout, "Episodes", "Field updates")
    assert any("Title e1" in line for line in lines), result.stdout


# Spec: | Additions | Same rule applied to available tracked fields |
def test_v1_addition_uses_available_fields(run_cli, make_vault, legacy, digest):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    result = run_cli("digest", "vault")
    lines = digest.group(result.stdout, "Entries", "Additions")
    assert any("Title e1" in line for line in lines), result.stdout


# ---------------------------------------------------------------------------
# | Removal Detection | v1: Not available | v2: Not available |
# "Not applicable; removals group is omitted entirely"
# ---------------------------------------------------------------------------

# Spec: | Removals | ... | Not applicable; removals group is omitted entirely |
def test_v1_digest_has_no_removals_group(run_cli, make_vault, legacy, digest):
    entry = legacy.v1_entry("e1")
    entry["removed"] = {legacy.V1_EPOCH: True}
    make_vault(legacy.v1_catalog(entries=[entry]))
    result = run_cli("digest", "vault")
    assert "Removals" not in result.stdout


# Spec: | Removals | ... | Not applicable; removals group is omitted entirely |
def test_v2_digest_has_no_removals_group(run_cli, make_vault, legacy, digest):
    entry = legacy.v2_entry("e1")
    entry["removed"] = {legacy.V2_STAMP: True}
    make_vault(legacy.v2_catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert "Removals" not in result.stdout


# Spec: | v3 | ... | Full removal detection | ... |
def test_v3_digest_has_a_removals_group(run_cli, make_vault, catalogs):
    entry = catalogs.entry("e1")
    entry["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert "Removals" in result.stdout


# ---------------------------------------------------------------------------
# | Priority | `1` Removals (v3 only) | `2` Additions | `3` Field updates |
# "Each entry may appear once."
# ---------------------------------------------------------------------------

# Spec: | `1` | Removals (v3 only) |
# Context: a removal that also has changed fields is reported as a removal.
def test_removal_wins_over_field_update(run_cli, make_vault, catalogs, digest):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "Old", catalogs.STAMP_2: "New"}
    entry["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert digest.group(result.stdout, "Episodes", "Removals")
    assert digest.group(result.stdout, "Episodes", "Field updates") == []


# Spec: | `1` | Removals (v3 only) | ... | `2` | Additions |
# Context: an entry whose only observation is `removed: true` qualifies under
# both rules; removals take priority.
def test_removal_wins_over_addition(run_cli, make_vault, catalogs, digest):
    entry = catalogs.entry("e1")
    entry["removed"] = {catalogs.STAMP_1: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert digest.group(result.stdout, "Episodes", "Removals")
    assert digest.group(result.stdout, "Episodes", "Additions") == []


# Spec: "Each entry may appear once."
def test_each_entry_appears_once(run_cli, make_vault, catalogs, digest):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "Old", catalogs.STAMP_2: "Unique Title"}
    entry["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert result.stdout.count("Unique Title") == 1


# Spec: "Each entry may appear once."
# Context: an addition is never also listed as a field update.
def test_addition_is_not_also_a_field_update(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    result = run_cli("digest", "vault")
    assert result.stdout.count("Title e1") == 1


# ---------------------------------------------------------------------------
# | v1 | Value at the latest key by **numeric** comparison of UNIX-epoch strings |
# ---------------------------------------------------------------------------

# Spec: | v1 | Value at the latest key by **numeric** comparison of UNIX-epoch
#   strings |
# Context: `"999999999"` sorts after `"1718444400"` lexicographically but
# before it numerically, so only numeric comparison yields the newer title.
def test_v1_current_value_uses_numeric_key_comparison(
    run_cli, make_vault, legacy, digest
):
    entry = legacy.v1_entry("e1")
    entry["title"] = {"999999999": "Older Title", "1718444400": "Newer Title"}
    make_vault(legacy.v1_catalog(entries=[entry]))
    result = run_cli("digest", "vault")
    assert "Newer Title" in result.stdout
    assert "Older Title" not in result.stdout


# Spec: | v1 history ordering in digest | Numeric comparison of epoch-second
#   strings |
# Context: the same comparison decides which two values are "the latest two".
def test_v1_field_update_uses_numeric_ordering(
    run_cli, make_vault, legacy, digest
):
    entry = legacy.v1_entry("e1")
    entry["views"] = {"999999999": 5, "1718444400": 5}
    make_vault(legacy.v1_catalog(entries=[entry]))
    result = run_cli("digest", "vault")
    assert digest.group(result.stdout, "Entries", "Field updates") == []


# Spec: | v2 | Value at the latest key by **lexicographic** comparison of ISO
#   8601 strings |
def test_v2_current_value_uses_lexicographic_key_comparison(
    run_cli, make_vault, legacy
):
    entry = legacy.v2_entry("e1")
    entry["title"] = {
        "2024-06-15T09:40:00": "Older Title",
        "2024-12-01T00:00:00": "Newer Title",
    }
    make_vault(legacy.v2_catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert "Newer Title" in result.stdout
    assert "Older Title" not in result.stdout


# Spec: | v3 | Value at the latest key by **lexicographic** comparison of ISO
#   8601 strings |
def test_v3_current_value_uses_lexicographic_key_comparison(
    run_cli, make_vault, catalogs
):
    entry = catalogs.entry("e1")
    entry["title"] = {
        "2024-06-15T09:40:00": "Older Title",
        "2024-12-01T00:00:00": "Newer Title",
    }
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert "Newer Title" in result.stdout
    assert "Older Title" not in result.stdout


# Spec: | History Key Format | v3 | ISO 8601 string keys |
# Context: file key order is irrelevant; the latest key wins.
def test_v3_file_key_order_does_not_decide_the_current_value(
    run_cli, make_vault, catalogs
):
    entry = catalogs.entry("e1")
    entry["title"] = {
        "2024-12-01T00:00:00": "Newer Title",
        "2024-06-15T09:40:00": "Older Title",
    }
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert "Newer Title" in result.stdout
    assert "Older Title" not in result.stdout


# ---------------------------------------------------------------------------
# | v1 | `https://media.example.com/channel/<source_id>` |
# | v2 | `source` field value | | v3 | `source` field value |
# ---------------------------------------------------------------------------

# Spec: | v1 | `https://media.example.com/channel/<source_id>` |
def test_v1_source_url_is_the_channel_template(
    run_cli, make_vault, legacy, digest
):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")],
                                 source_id="chan-7"))
    result = run_cli("digest", "vault")
    assert legacy.v1_source("chan-7") in digest.trailing(result.stdout)


# Spec: | v2 | `source` field value |
def test_v2_source_url_is_the_source_field(
    run_cli, make_vault, legacy, source, digest
):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    result = run_cli("digest", "vault")
    assert source.url in digest.trailing(result.stdout)


# Spec: | v3 | `source` field value |
def test_v3_source_url_is_the_source_field(
    run_cli, make_vault, catalogs, source, digest
):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    result = run_cli("digest", "vault")
    assert source.url in digest.trailing(result.stdout)


# Spec: | Source reference | The trailing line includes the resolved source URL
#   for the loaded vault version |
# Context: a v1 vault never reports a `source` field, because it has none.
def test_v1_trailing_line_does_not_use_a_source_field(
    run_cli, make_vault, legacy, digest
):
    catalog = legacy.v1_catalog(entries=[legacy.v1_entry("e1")],
                                source_id="chan-7")
    catalog["source"] = "https://wrong.example.com/ignored"
    make_vault(catalog)
    result = run_cli("digest", "vault")
    assert "wrong.example.com" not in result.stdout
    assert legacy.v1_source("chan-7") in digest.trailing(result.stdout)
