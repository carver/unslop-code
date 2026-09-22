"""Spec sections: `digest` Format-Aware Loading, `digest` Current Value Resolution,
`digest` Source URL Resolution."""

from conftest import (
    V1_EPOCH,
    read_catalog,
    V1_SOURCE_TEMPLATE,
    V2_LATER,
    V2_STAMP,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

#: Two epoch keys whose numeric order is the reverse of their lexicographic order.
EPOCH_EARLY = "999999999"
EPOCH_LATE = "1000000000"


# Spec: v1 | Category Grouping | Single group: `Entries`
def test_v1_uses_a_single_entries_group(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    stdout = run("digest", "vault").stdout
    assert "Entries" in stdout
    assert "Episodes" not in stdout


# Spec: `digest` must work directly on v1 ... catalogs without migrating
def test_v1_digest_leaves_the_catalog_at_version_one(run, tmp_path):
    vault = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    assert run("digest", "vault").returncode == 0
    assert read_catalog(vault)["version"] == 1


# Spec: v1 | Removal Detection | Not available (no `removed` field)
def test_v1_never_reports_removals(run, tmp_path):
    entry = v1_entry("e1", removed={V1_EPOCH: True})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Removed" not in stdout
    assert "Added" in stdout


# Spec: v1 | History Key Format | UNIX-epoch string keys
# Spec: v1 | Value at the latest key by **numeric** comparison of UNIX-epoch strings
def test_v1_current_value_uses_numeric_key_order(run, tmp_path):
    entry = v1_entry("e1", title={EPOCH_EARLY: "Earlier title", EPOCH_LATE: "Later title"})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Later title" in stdout
    assert "Earlier title" not in stdout


# Spec: v1 history ordering in digest | Numeric comparison of epoch-second strings
# (the two latest values are also picked numerically when classifying an update)
def test_v1_update_compares_the_numerically_latest_two_values(run, tmp_path):
    entry = v1_entry("e1", title={EPOCH_EARLY: "Earlier title", EPOCH_LATE: "Later title"})
    write_vault(tmp_path, v1_catalog(entries=[entry]))
    stdout = run("digest", "vault").stdout
    assert "(title)" in stdout


# Spec: v1 | Source URL | `https://media.example.com/channel/<source_id>`
def test_v1_trailing_line_uses_the_derived_source_url(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")], source_id="chan-7"))
    assert V1_SOURCE_TEMPLATE.format("chan-7") in run("digest", "vault").stdout


# Spec: v2 | Category Grouping | `Episodes`, `Streams`, `Clips`
def test_v2_groups_by_category(run, tmp_path):
    catalog = v2_catalog(episodes=[v2_entry("e1")], streams=[v2_entry("s1")], clips=[v2_entry("c1")])
    write_vault(tmp_path, catalog)
    stdout = run("digest", "vault").stdout
    assert "Episodes" in stdout
    assert "Streams" in stdout
    assert "Clips" in stdout
    assert "Entries" not in stdout


# Spec: v2 | Removal Detection | Not available (no `removed` field)
def test_v2_never_reports_removals(run, tmp_path):
    entry = v2_entry("e1", removed={V2_STAMP: True})
    write_vault(tmp_path, v2_catalog(episodes=[entry]))
    assert "Removed" not in run("digest", "vault").stdout


# Spec: v2 | History Key Format | ISO 8601 string keys; latest key lexicographically
def test_v2_current_value_uses_the_latest_iso_key(run, tmp_path):
    entry = v2_entry("e1", title={V2_STAMP: "Older title", V2_LATER: "Newest title"})
    write_vault(tmp_path, v2_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Newest title" in stdout
    assert "Older title" not in stdout


# Spec: v2 | Source URL | `source` field value
def test_v2_trailing_line_uses_the_source_field(run, tmp_path):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source="http://v2.invalid/s.json"))
    assert "http://v2.invalid/s.json" in run("digest", "vault").stdout


# Spec: v3 | Category Grouping | `Episodes`, `Streams`, `Clips`
def test_v3_groups_by_category(run, tmp_path):
    catalog = v3_catalog(streams=[v3_entry("s1")], clips=[v3_entry("c1")])
    write_vault(tmp_path, catalog)
    stdout = run("digest", "vault").stdout
    assert "Streams" in stdout
    assert "Clips" in stdout


# Spec: v3 | Removal Detection | Full removal detection
def test_v3_detects_removals(run, tmp_path):
    entry = v3_entry("e1", removed={V2_STAMP: False, V2_LATER: True})
    write_vault(tmp_path, v3_catalog(clips=[entry]))
    assert "Removed" in run("digest", "vault").stdout


# Spec: v3 | Source URL | `source` field value
def test_v3_trailing_line_uses_the_source_field(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")], source="http://v3.invalid/s.json"))
    assert "http://v3.invalid/s.json" in run("digest", "vault").stdout


# Spec: Input | Existing vault of any supported version (v1/v2 need no prior migration)
def test_digest_works_on_every_supported_version(run, tmp_path):
    catalogs = {
        "one": v1_catalog(entries=[v1_entry("e1")]),
        "two": v2_catalog(episodes=[v2_entry("e1")]),
        "three": v3_catalog(episodes=[v3_entry("e1")]),
    }
    for name, catalog in catalogs.items():
        write_vault(tmp_path, catalog, name=name)
        result = run("digest", name)
        assert result.returncode == 0, result.stderr
        assert "Title e1" in result.stdout


# Spec: v1/v2 Qualification Rule | Same rule applied to available tracked fields
def test_v1_addition_ignores_the_absent_removed_field(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    assert "Added" in run("digest", "vault").stdout


# Spec: v1/v2 Qualification Rule | Same rule applied to available tracked fields
def test_v2_update_uses_available_fields_only(run, tmp_path):
    entry = v2_entry("e1", likes={V2_STAMP: 2, V2_LATER: 8})
    write_vault(tmp_path, v2_catalog(episodes=[entry]))
    assert "(likes)" in run("digest", "vault").stdout
