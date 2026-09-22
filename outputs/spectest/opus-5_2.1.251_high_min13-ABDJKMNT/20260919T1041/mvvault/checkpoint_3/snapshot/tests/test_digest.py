"""`digest` Command: format-aware loading, classification, precedence and layout."""

import json

import pytest

from conftest import V1_SOURCE_URL, v1_catalog, v1_entry, v2_catalog, v2_entry, v3_catalog, v3_entry

T1 = "2024-01-01T00:00:00"
T2 = "2024-02-01T00:00:00"
T3 = "2024-03-01T00:00:00"

SOURCE = "http://source.invalid/feed.json"

#: Headers the layout may use for a category section.
CATEGORY_HEADERS = ("Entries", "Episodes", "Streams", "Clips")


@pytest.fixture
def digest(run_cli, make_vault):
    """Write a catalog and return the successful `digest` output for it."""

    def run(catalog, name="v"):
        make_vault(catalog, name)
        result = run_cli("digest", name)
        assert result.returncode == 0, result.stderr
        return result.stdout

    return run


def line_for(output, title):
    """The single output line naming `title`."""
    matches = [line for line in output.splitlines() if title in line]
    assert len(matches) == 1, output
    return matches[0]


def titles_after(output, header):
    """Entry lines listed under `header`, up to the next header of any kind."""
    lines = output.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == header)
    listed = []
    for line in lines[start + 1 :]:
        if not line.startswith("    "):
            break
        listed.append(line.strip().lstrip("- "))
    return listed


# Spec: Syntax | `python mvault.py digest <name>`
def test_digest_runs_on_a_vault(run_cli, make_vault):
    make_vault(v3_catalog(SOURCE, episodes=[v3_entry("a")]))
    assert run_cli("digest", "v").returncode == 0


# Spec: Output stream | stdout
def test_digest_writes_to_stdout(run_cli, make_vault):
    make_vault(v3_catalog(SOURCE, episodes=[v3_entry("a")]))
    result = run_cli("digest", "v")
    assert result.stdout.strip()
    assert result.stderr == ""


# Spec: `digest` is read-only; it never writes `catalog.json` or `catalog.bak`
def test_digest_does_not_write_the_catalog(run_cli, make_vault):
    vault = make_vault(v3_catalog(SOURCE, episodes=[v3_entry("a")]))
    before = (vault / "catalog.json").read_text()
    run_cli("digest", "v")
    assert (vault / "catalog.json").read_text() == before
    assert not (vault / "catalog.bak").exists()


# Spec: The `digest` command works on vaults of any supported version without
# requiring prior migration.
@pytest.mark.parametrize(
    "catalog",
    [
        v1_catalog([v1_entry("a")]),
        v2_catalog(SOURCE, episodes=[v2_entry("a")]),
        v3_catalog(SOURCE, episodes=[v3_entry("a")]),
    ],
)
def test_digest_reads_every_supported_version(run_cli, make_vault, catalog):
    make_vault(catalog)
    assert run_cli("digest", "v").returncode == 0


# Spec: `digest` must work directly on v1, v2, and v3 catalogs without migrating.
@pytest.mark.parametrize("catalog", [v1_catalog([v1_entry("a")]), v2_catalog(SOURCE, episodes=[v2_entry("a")])])
def test_digest_leaves_legacy_catalogs_at_their_version(run_cli, make_vault, catalog):
    vault = make_vault(catalog)
    run_cli("digest", "v")
    assert json.loads((vault / "catalog.json").read_text())["version"] == catalog["version"]


# Spec: v1 | Category Grouping | Single group: `Entries`
def test_v1_groups_everything_under_entries(digest):
    output = digest(v1_catalog([v1_entry("a")]))
    assert "Entries" in output
    assert "Episodes" not in output


# Spec: v2 | Category Grouping | `Episodes`, `Streams`, `Clips`
def test_v2_groups_by_category(digest):
    output = digest(v2_catalog(SOURCE, episodes=[v2_entry("e")], streams=[v2_entry("s")], clips=[v2_entry("c")]))
    assert ["Episodes", "Streams", "Clips"] == [line for line in output.splitlines() if line in CATEGORY_HEADERS]


# Spec: v3 | Category Grouping | `Episodes`, `Streams`, `Clips`
def test_v3_groups_by_category(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("e")], streams=[v3_entry("s")], clips=[v3_entry("c")]))
    assert ["Episodes", "Streams", "Clips"] == [line for line in output.splitlines() if line in CATEGORY_HEADERS]


# Spec: v1 | Removal Detection | Not available (no `removed` field)
def test_v1_never_reports_removals(digest):
    output = digest(v1_catalog([v1_entry("a", views={"1000": 1, "2000": 2})]))
    assert "Removed" not in output


# Spec: v2 | Removal Detection | Not available (no `removed` field)
def test_v2_never_reports_removals(digest):
    output = digest(v2_catalog(SOURCE, episodes=[v2_entry("a", views={T1: 1, T2: 2})]))
    assert "Removed" not in output


# Spec: v1 | History Key Format | UNIX-epoch string keys
def test_v1_reads_epoch_keys(digest):
    output = digest(v1_catalog([v1_entry("a", title={"1000000000": "old", "1000000001": "new"})]))
    assert "new" in output


# Spec: v2 | History Key Format | ISO 8601 string keys
def test_v2_reads_iso_keys(digest):
    output = digest(v2_catalog(SOURCE, episodes=[v2_entry("a", title={T1: "old", T2: "new"})]))
    assert "new" in output


# Spec: Additions | Entry has only initial observations; no tracked field has a second
# history entry
def test_additions_are_entries_with_only_initial_observations(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a")]))
    assert titles_after(output, "Added:") == ["title-a"]


# Spec: Additions | ... (an entry with a second history entry is not an addition)
def test_entry_with_a_second_history_entry_is_not_an_addition(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a", views={T1: 1, T2: 2})]))
    assert "Added" not in output


# Spec: Additions | Same rule applied to available tracked fields (v1/v2)
def test_v1_and_v2_additions_use_the_available_fields(digest):
    assert titles_after(digest(v1_catalog([v1_entry("a")])), "Added:") == ["title-a"]
    assert titles_after(digest(v2_catalog(SOURCE, episodes=[v2_entry("a")])), "Added:") == ["title-a"]


# Spec: Removals | Latest `removed` value is `true` and prior `removed` value, if
# present, is `false`
def test_removals_need_a_latest_true_after_false(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a", removed={T1: False, T2: True})]))
    assert titles_after(output, "Removed:") == ["title-a"]


# Spec: Removals | ... prior `removed` value, if present, is `false` (a re-removal is
# not reported again)
def test_entry_removed_before_and_still_removed_is_not_a_removal(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a", removed={T1: True, T2: True})]))
    assert "Removed" not in output


# Spec: Removals | Not applicable; removals group is omitted entirely (v1/v2)
def test_removals_group_is_absent_for_legacy_vaults(digest):
    assert "Removed" not in digest(v1_catalog([v1_entry("a")]))
    assert "Removed" not in digest(v2_catalog(SOURCE, episodes=[v2_entry("a")]))


# Spec: Field updates | At least one tracked field has two or more history entries and
# the latest two values differ
def test_field_updates_report_the_changed_field(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a", views={T1: 1, T2: 2})]))
    assert "views" in line_for(output, "title-a")


# Spec: Field updates | ... the latest two values differ (equal latest values are not a
# change)
def test_repeated_value_is_not_a_field_update(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a", views={T1: 1, T2: 1})]))
    assert "title-a" not in output


# Spec: Field-update suffix | Changed field names in parentheses after title
def test_changed_field_names_follow_the_title_in_parentheses(digest):
    entry = v3_entry("a", views={T1: 1, T2: 2}, likes={T1: 5, T2: 6})
    output = digest(v3_catalog(SOURCE, episodes=[entry]))
    line = line_for(output, "title-a")
    assert "(" in line and ")" in line
    assert "views" in line and "likes" in line


# Spec: Entry text | Current title from latest `title` history value
def test_entry_text_uses_the_latest_title(digest):
    entry = v3_entry("a", title={T1: "old name", T2: "new name"})
    output = digest(v3_catalog(SOURCE, episodes=[entry]))
    assert "new name" in output
    assert "old name" not in output


# Spec: Priority `1` | Removals (v3 only) — over a field update
def test_removal_outranks_a_field_update(digest):
    entry = v3_entry("a", removed={T1: False, T2: True}, views={T1: 1, T2: 2})
    output = digest(v3_catalog(SOURCE, episodes=[entry]))
    assert titles_after(output, "Removed:") == ["title-a"]
    assert "Updated" not in output


# Spec: Priority `1` | Removals (v3 only) — over an addition
def test_removal_outranks_an_addition(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a", removed={T1: True})]))
    assert titles_after(output, "Removed:") == ["title-a"]
    assert "Added" not in output


# Spec: Each entry may appear once.
def test_each_entry_appears_once(digest):
    entry = v3_entry("a", removed={T1: False, T2: True}, views={T1: 1, T2: 2}, title={T1: "x", T2: "target"})
    output = digest(v3_catalog(SOURCE, episodes=[entry]))
    assert output.count("target") == 1


# Spec: Priority `2` | Additions — an addition is never listed as a field update
def test_addition_is_not_listed_as_a_field_update(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a")]))
    assert "Updated" not in output


# Spec: v1 | Value at the latest key by **numeric** comparison of UNIX-epoch strings
def test_v1_resolves_current_value_numerically(digest):
    entry = v1_entry("a", title={"999999999": "lexicographically largest", "1000000000": "numerically latest"})
    output = digest(v1_catalog([entry]))
    assert "numerically latest" in output
    assert "lexicographically largest" not in output


# Spec: v2 | Value at the latest key by **lexicographic** comparison of ISO 8601 strings
def test_v2_resolves_current_value_lexicographically(digest):
    entry = v2_entry("a", title={"2024-01-01T00:00:00": "older", "2024-10-01T00:00:00": "newer"})
    output = digest(v2_catalog(SOURCE, episodes=[entry]))
    assert "newer" in output and "older" not in output


# Spec: v3 | Value at the latest key by **lexicographic** comparison of ISO 8601 strings
def test_v3_resolves_current_value_lexicographically(digest):
    entry = v3_entry("a", title={"2024-01-01T00:00:00": "older", "2024-10-01T00:00:00": "newer"})
    output = digest(v3_catalog(SOURCE, episodes=[entry]))
    assert "newer" in output and "older" not in output


# Spec: v1 | Source URL | `https://media.example.com/channel/<source_id>`
def test_v1_source_url_is_derived(digest):
    assert V1_SOURCE_URL in digest(v1_catalog([v1_entry("a")]))


# Spec: v2 | Source URL | `source` field value
def test_v2_source_url_is_the_source_field(digest):
    assert SOURCE in digest(v2_catalog(SOURCE, episodes=[v2_entry("a")]))


# Spec: v3 | Source URL | `source` field value
def test_v3_source_url_is_the_source_field(digest):
    assert SOURCE in digest(v3_catalog(SOURCE, episodes=[v3_entry("a")]))


# Spec: Source reference | The trailing line includes the resolved source URL for the
# loaded vault version
def test_source_url_is_on_the_trailing_line(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a")]))
    assert SOURCE in output.splitlines()[-1]


# Spec: Trailing line | Metadata about the digest run
def test_trailing_line_names_the_vault_and_version(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a")]))
    trailing = output.splitlines()[-1]
    assert "v" in trailing and "3" in trailing


# Spec: Grouping within category | Changes grouped by type
def test_changes_are_grouped_by_type_within_a_category(digest):
    catalog = v3_catalog(
        SOURCE,
        episodes=[
            v3_entry("new", published="2024-05-01T00:00:00"),
            v3_entry("gone", published="2024-04-01T00:00:00", removed={T1: False, T2: True}),
            v3_entry("changed", published="2024-03-01T00:00:00", views={T1: 1, T2: 2}),
        ],
    )
    output = digest(catalog)
    assert titles_after(output, "Removed:") == ["title-gone"]
    assert titles_after(output, "Added:") == ["title-new"]
    assert [title.split(" (")[0] for title in titles_after(output, "Updated:")] == ["title-changed"]


# Spec: Empty category | Omitted
def test_empty_categories_are_omitted(digest):
    output = digest(v3_catalog(SOURCE, episodes=[v3_entry("a")]))
    assert "Streams" not in output and "Clips" not in output


# Spec: Empty category | Omitted (a category whose entries qualify for nothing)
def test_category_without_qualifying_entries_is_omitted(digest):
    catalog = v3_catalog(SOURCE, episodes=[v3_entry("a")], streams=[v3_entry("s", views={T1: 1, T2: 1})])
    assert "Streams" not in digest(catalog)


# Spec: No notable changes anywhere | Indicate that no notable changes were found
def test_no_notable_changes_is_reported(digest):
    output = digest(v3_catalog(SOURCE))
    assert "no notable changes" in output.lower()


# Spec: Reappearance after removal (v3 only) | Indicate reappearance alongside any
# other changed fields
def test_reappearance_is_indicated(digest):
    entry = v3_entry("a", removed={T1: False, T2: True, T3: False})
    output = digest(v3_catalog(SOURCE, episodes=[entry]))
    assert "reappear" in line_for(output, "title-a").lower()


# Spec: Reappearance after removal (v3 only) | ... alongside any other changed fields
def test_reappearance_lists_other_changed_fields_too(digest):
    entry = v3_entry("a", removed={T1: False, T2: True, T3: False}, views={T1: 1, T3: 9})
    line = line_for(digest(v3_catalog(SOURCE, episodes=[entry])), "title-a")
    assert "reappear" in line.lower() and "views" in line


# Spec: Missing vault | Error to stderr including vault name; exit non-zero
def test_digest_on_missing_vault_errors_with_the_name(run_cli):
    result = run_cli("digest", "ghost")
    assert result.returncode != 0
    assert "ghost" in result.stderr
    assert result.stdout == ""


# Spec: `digest` on vault with unsupported version | stderr | non-zero | Message
# includes version value
def test_digest_on_unsupported_version_names_the_version(run_cli, make_vault):
    make_vault({"version": 9, "source": SOURCE, "episodes": [], "streams": [], "clips": []})
    result = run_cli("digest", "v")
    assert result.returncode != 0
    assert "9" in result.stderr
