"""Spec sections: `digest` Command, format-aware loading, classification, layout."""

import json

from conftest import (
    V1_KEY,
    V2_KEY,
    V2_OLDER_KEY,
    catalog_bytes,
    run_cli,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

LATER_KEY = "2024-11-02T00:00:00"
LATEST_KEY = "2024-12-24T00:00:00"


def digest(tmp_path):
    result = run_cli("digest", "demo", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return result


# `digest` Command: "Syntax | `python mvault.py digest <name>`"; "Output stream
# | stdout"; "Input | Existing vault of any supported version".
def test_digest_writes_a_summary_to_stdout(tmp_path):
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[v3_entry("e1")]))

    result = digest(tmp_path)
    assert "title-e1" in result.stdout
    assert result.stderr == ""


# `digest` Command: "Catalog modification | `digest` is read-only; it never
# writes `catalog.json` or `catalog.bak`".
def test_digest_never_writes_the_catalog(tmp_path):
    vault = write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[v3_entry("e1")]))
    before = catalog_bytes(vault)

    digest(tmp_path)
    assert catalog_bytes(vault) == before
    assert not (vault / "catalog.bak").exists()


# `digest` Format-Aware Loading: "`digest` must work directly on v1, v2 and v3
# catalogs without migrating" — the catalog keeps its on-disk version.
def test_digest_does_not_migrate_legacy_vaults(tmp_path):
    vault = write_vault(tmp_path, v1_catalog([v1_entry("e1")]))

    digest(tmp_path)
    assert json.loads(catalog_bytes(vault))["version"] == 1


# `digest` Format-Aware Loading: "v1 | Single group: `Entries`".
def test_v1_groups_everything_under_entries(tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]))

    stdout = digest(tmp_path).stdout
    assert "Entries" in stdout
    assert "Episodes" not in stdout


# `digest` Format-Aware Loading: "v2 | `Episodes`, `Streams`, `Clips`".
def test_v2_groups_by_category(tmp_path):
    catalog = v2_catalog(
        "https://example.test/v2",
        episodes=[v2_entry("e1")],
        streams=[v2_entry("s1")],
        clips=[v2_entry("c1")],
    )
    write_vault(tmp_path, catalog)

    stdout = digest(tmp_path).stdout
    assert "Episodes" in stdout
    assert "Streams" in stdout
    assert "Clips" in stdout


# `digest` Format-Aware Loading: "v1 | ... Removal detection | Not available (no
# `removed` field)"; `digest` Change Classification: "Removals ... Not
# applicable; removals group is omitted entirely".
def test_v1_never_reports_removals(tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]))

    assert "Removal" not in digest(tmp_path).stdout


# `digest` Current Value Resolution: "v1 | Value at the latest key by **numeric**
# comparison of UNIX-epoch strings" — `999999999` is lexicographically greatest
# but numerically older than `1700000000`.
def test_v1_resolves_the_current_value_numerically(tmp_path):
    entry = v1_entry("e1", title={"999999999": "older title", "1700000000": "newer title"})
    write_vault(tmp_path, v1_catalog([entry]))

    stdout = digest(tmp_path).stdout
    assert "newer title" in stdout
    assert "older title" not in stdout


# `digest` Current Value Resolution: "v2 | Value at the latest key by
# **lexicographic** comparison of ISO 8601 strings".
def test_v2_resolves_the_current_value_lexicographically(tmp_path):
    entry = v2_entry("e1", title={V2_OLDER_KEY: "older title", V2_KEY: "newer title"})
    write_vault(tmp_path, v2_catalog("https://example.test/v2", episodes=[entry]))

    stdout = digest(tmp_path).stdout
    assert "newer title" in stdout
    assert "older title" not in stdout


# `digest` Current Value Resolution: "v3 | Value at the latest key by
# **lexicographic** comparison of ISO 8601 strings"; Output Layout: "Entry text |
# Current title from latest `title` history value".
def test_v3_entry_text_is_the_latest_title(tmp_path):
    entry = v3_entry("e1", title={V2_KEY: "older title", LATER_KEY: "newer title"})
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    stdout = digest(tmp_path).stdout
    assert "newer title" in stdout
    assert "older title" not in stdout


# `digest` Change Classification: "Additions | Entry has only initial
# observations; no tracked field has a second history entry".
def test_an_entry_with_only_initial_observations_is_an_addition(tmp_path):
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[v3_entry("e1")]))

    stdout = digest(tmp_path).stdout
    assert "Additions" in stdout
    assert "title-e1" in stdout


# `digest` Change Classification: "Additions | ... Same rule applied to available
# tracked fields" for v1/v2.
def test_v2_additions_use_the_available_tracked_fields(tmp_path):
    write_vault(tmp_path, v2_catalog("https://example.test/v2", episodes=[v2_entry("e1")]))

    assert "Additions" in digest(tmp_path).stdout


# `digest` Change Classification: "Removals | Latest `removed` value is `true`
# and prior `removed` value, if present, is `false`".
def test_an_entry_removed_after_being_present_is_a_removal(tmp_path):
    entry = v3_entry("e1", removed={V2_KEY: False, LATER_KEY: True})
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    stdout = digest(tmp_path).stdout
    assert "Removals" in stdout
    assert "title-e1" in stdout


# `digest` Change Classification: "Field updates | At least one tracked field has
# two or more history entries and the latest two values differ".
def test_a_changed_field_is_a_field_update(tmp_path):
    entry = v3_entry("e1", views={V2_KEY: 10, LATER_KEY: 25})
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    stdout = digest(tmp_path).stdout
    assert "Field updates" in stdout
    assert "Additions" not in stdout


# `digest` Change Classification: "Field updates | ... the latest two values
# differ" — a repeated value is not a change, so nothing is reported.
def test_a_repeated_value_is_not_a_field_update(tmp_path):
    entry = v3_entry("e1", views={V2_KEY: 10, LATER_KEY: 10})
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    stdout = digest(tmp_path).stdout
    assert "title-e1" not in stdout


# `digest` Output Layout: "Field-update suffix | Changed field names in
# parentheses after title".
def test_field_updates_name_the_changed_fields(tmp_path):
    entry = v3_entry(
        "e1",
        views={V2_KEY: 10, LATER_KEY: 25},
        description={V2_KEY: "old", LATER_KEY: "new"},
    )
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    line = next(line for line in digest(tmp_path).stdout.splitlines() if "title-e1" in line)
    assert "views" in line.split("(", 1)[1]
    assert "description" in line.split("(", 1)[1]
    assert "likes" not in line


# `digest` Output Layout: "Reappearance after removal (v3 only) | Indicate
# reappearance alongside any other changed fields".
def test_reappearance_is_indicated_with_other_changed_fields(tmp_path):
    entry = v3_entry(
        "e1",
        removed={V2_KEY: False, LATER_KEY: True, LATEST_KEY: False},
        views={V2_KEY: 10, LATEST_KEY: 25},
    )
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    stdout = digest(tmp_path).stdout
    line = next(line for line in stdout.splitlines() if "title-e1" in line)
    assert "reappear" in line.lower()
    assert "views" in line
    assert "Removals" not in stdout


# `digest` Group Precedence: "Each entry may appear once"; "`1` | Removals (v3
# only)" outranks additions for an entry whose only observation is `removed:
# true`.
def test_removal_outranks_addition(tmp_path):
    entry = v3_entry("e1", removed={V2_KEY: True})
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    stdout = digest(tmp_path).stdout
    assert stdout.count("title-e1") == 1
    assert "Removals" in stdout
    assert "Additions" not in stdout


# `digest` Group Precedence: "`1` | Removals" outranks field updates for an
# entry that also changed a tracked field.
def test_removal_outranks_field_updates(tmp_path):
    entry = v3_entry(
        "e1",
        removed={V2_KEY: False, LATER_KEY: True},
        views={V2_KEY: 10, LATER_KEY: 25},
    )
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    stdout = digest(tmp_path).stdout
    assert stdout.count("title-e1") == 1
    assert "Field updates" not in stdout


# `digest` Output Layout: "Grouping within category | Changes grouped by type"
# and Determinism: "Digest group order | Deterministic" — removals, then
# additions, then field updates.
def test_groups_follow_the_precedence_order(tmp_path):
    entries = [
        v3_entry("e1", removed={V2_KEY: False, LATER_KEY: True}),
        v3_entry("e2"),
        v3_entry("e3", views={V2_KEY: 10, LATER_KEY: 25}),
    ]
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=entries))

    stdout = digest(tmp_path).stdout
    assert stdout.index("Removals") < stdout.index("Additions") < stdout.index("Field updates")


# Determinism: "Digest category order | Deterministic" — categories keep the
# catalog's own order.
def test_categories_follow_a_fixed_order(tmp_path):
    catalog = v3_catalog(
        "https://example.test/a",
        episodes=[v3_entry("e1")],
        streams=[v3_entry("s1")],
        clips=[v3_entry("c1")],
    )
    write_vault(tmp_path, catalog)

    stdout = digest(tmp_path).stdout
    assert stdout.index("Episodes") < stdout.index("Streams") < stdout.index("Clips")


# Determinism: "Digest entry order | Deterministic" — repeated runs of an
# unchanged vault print identical output.
def test_digest_output_is_stable_across_runs(tmp_path):
    entries = [v3_entry(f"e{n}", published=f"2024-01-0{n}T00:00:00") for n in (1, 2, 3)]
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=entries))

    assert digest(tmp_path).stdout == digest(tmp_path).stdout


# `digest` Output Layout: "Empty category | Omitted".
def test_categories_without_changes_are_omitted(tmp_path):
    catalog = v3_catalog("https://example.test/a", episodes=[v3_entry("e1")])
    write_vault(tmp_path, catalog)

    stdout = digest(tmp_path).stdout
    assert "Streams" not in stdout
    assert "Clips" not in stdout


# `digest` Output Layout: "No notable changes anywhere | Indicate that no
# notable changes were found".
def test_a_vault_without_notable_changes_says_so(tmp_path):
    entry = v3_entry("e1", views={V2_KEY: 10, LATER_KEY: 10})
    write_vault(tmp_path, v3_catalog("https://example.test/a", episodes=[entry]))

    assert "no notable changes" in digest(tmp_path).stdout.lower()


# `digest` Output Layout: "Trailing line | Metadata about the digest run" and
# "Source reference | The trailing line includes the resolved source URL";
# `digest` Source URL Resolution: "v3 | `source` field value".
def test_trailing_line_carries_the_v3_source(tmp_path):
    write_vault(tmp_path, v3_catalog("https://example.test/v3", episodes=[v3_entry("e1")]))

    assert digest(tmp_path).stdout.strip().splitlines()[-1].count("https://example.test/v3") == 1


# `digest` Source URL Resolution: "v2 | `source` field value".
def test_trailing_line_carries_the_v2_source(tmp_path):
    write_vault(tmp_path, v2_catalog("https://example.test/v2", episodes=[v2_entry("e1")]))

    assert "https://example.test/v2" in digest(tmp_path).stdout.strip().splitlines()[-1]


# `digest` Source URL Resolution: "v1 |
# `https://media.example.com/channel/<source_id>`".
def test_trailing_line_carries_the_v1_source_template(tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")], source_id="chan-7"))

    trailing = digest(tmp_path).stdout.strip().splitlines()[-1]
    assert "https://media.example.com/channel/chan-7" in trailing


# Error Handling: "Missing vault for `digest` | stderr | non-zero | Message
# includes vault name".
def test_missing_vault_is_an_error_naming_the_vault(tmp_path):
    result = run_cli("digest", "absent", cwd=tmp_path)
    assert result.returncode != 0
    assert "absent" in result.stderr
    assert result.stdout == ""


# Error Handling: "`digest` on vault with unsupported version | stderr |
# non-zero | Message includes version value".
def test_unsupported_version_is_an_error_naming_the_version(tmp_path):
    catalog = v3_catalog("https://example.test/a", episodes=[])
    catalog["version"] = 9
    write_vault(tmp_path, catalog)

    result = run_cli("digest", "demo", cwd=tmp_path)
    assert result.returncode != 0
    assert "9" in result.stderr


# `digest` Format-Aware Loading: "v1 | ... History Key Format | UNIX-epoch string
# keys" — an entry whose epoch-keyed history changed is a field update.
def test_v1_field_updates_use_epoch_keys(tmp_path):
    entry = v1_entry("e1", views={V1_KEY: 10, "1800000000": 25})
    write_vault(tmp_path, v1_catalog([entry]))

    stdout = digest(tmp_path).stdout
    assert "Field updates" in stdout
    line = next(line for line in stdout.splitlines() if "title-e1" in line)
    assert "views" in line
