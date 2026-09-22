"""Spec sections: `digest` Command / Format-Aware Loading / Change
Classification / Group Precedence / Current Value Resolution / Source URL
Resolution / Output Layout / Determinism."""
import json
import os

import pytest
from conftest import (V1_SOURCE_PREFIX, entry_lines, has_backup, make_vault,
                      read_catalog, section_of, write_raw)

T1 = "2024-01-01T00:00:00"
T2 = "2024-02-01T00:00:00"
T3 = "2024-03-01T00:00:00"

# Numeric and lexicographic order disagree for this pair: numerically
# 1000000000 > 999999999, lexicographically "999999999" > "1000000000".
E_OLD = "999999999"
E_NEW = "1000000000"

DEFAULTS = {"title": "T", "description": "D", "views": 1, "likes": 1,
            "preview": "p"}


def item(eid, stamp=T1, removed=None, version=3, **fields):
    """A catalog entry whose tracked histories are given verbatim.

    Any field passed as a dict is used as its whole history; anything else is
    recorded as a single observation at `stamp`.
    """
    built = {"id": eid, "published": "2024-01-01T00:00:00",
             "width": 1920, "height": 1080}
    for field, default in DEFAULTS.items():
        value = fields.get(field, default)
        built[field] = value if isinstance(value, dict) else {stamp: value}
    if version == 3:
        built["removed"] = removed if removed is not None else {stamp: False}
        built["annotations"] = []
    return built


def v1_item(eid, stamp=E_OLD, **fields):
    built = item(eid, stamp=stamp, version=1, **fields)
    return built


def v1_vault(tmp_path, entries, name="v", source_id="chan42"):
    return make_vault(tmp_path, name,
                      {"version": 1, "source_id": source_id,
                       "entries": list(entries)})


def v2_vault(tmp_path, episodes=(), streams=(), clips=(), name="v",
             source="http://example.invalid/feed.json"):
    return make_vault(tmp_path, name,
                      {"version": 2, "source": source,
                       "episodes": list(episodes), "streams": list(streams),
                       "clips": list(clips)})


def v3_vault(tmp_path, episodes=(), streams=(), clips=(), name="v",
             source="http://example.invalid/feed.json"):
    catalog = {"version": 3, "source": source, "episodes": list(episodes),
               "streams": list(streams), "clips": list(clips)}
    return make_vault(tmp_path, name, catalog)


def digest(run, name="v"):
    result = run("digest", name)
    assert result.returncode == 0, result.stderr
    return result.stdout


# --------------------------------------------------------------------------
# `digest` Command
# --------------------------------------------------------------------------

# Phrase: "Syntax | `python mvault.py digest <name>`"
def test_digest_runs_on_a_vault(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1")])
    result = run("digest", "v")
    assert result.returncode == 0, result.stderr


# Phrase: "Output stream | stdout"
def test_digest_writes_to_stdout(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Pilot")])
    result = run("digest", "v")
    assert result.stdout.strip()
    assert "Pilot" in result.stdout


# Phrase: "Missing vault | Error to stderr including vault name; exit non-zero"
def test_digest_missing_vault_errors_with_name(run, tmp_path):
    result = run("digest", "ghostvault")
    assert result.returncode != 0
    assert "ghostvault" in result.stderr
    assert "ghostvault" not in result.stdout


# Phrase: "Catalog modification | `digest` is read-only; it never writes
#          `catalog.json` or `catalog.bak`"
@pytest.mark.parametrize("version", [1, 2, 3])
def test_digest_never_writes_catalog_or_backup(run, tmp_path, version):
    if version == 1:
        vault = v1_vault(tmp_path, [v1_item("e1")])
    elif version == 2:
        vault = v2_vault(tmp_path, episodes=[item("e1", version=2)])
    else:
        vault = v3_vault(tmp_path, episodes=[item("e1")])
    before = (vault / "catalog.json").read_bytes()

    assert run("digest", "v").returncode == 0

    assert (vault / "catalog.json").read_bytes() == before
    assert not has_backup(vault)


# Phrase: "The `digest` command works on vaults of any supported version
#          without requiring prior migration."
# Context: a v1 catalog is still a v1 catalog afterwards.
def test_digest_does_not_migrate_the_vault(run, tmp_path):
    vault = v1_vault(tmp_path, [v1_item("e1")])
    assert run("digest", "v").returncode == 0
    assert read_catalog(vault)["version"] == 1
    assert "entries" in read_catalog(vault)


# Phrase: "`digest` on vault with unsupported version | stderr | non-zero |
#          Message includes version value"
@pytest.mark.parametrize("version", [0, 4, 99])
def test_digest_unsupported_version_reports_the_value(run, tmp_path, version):
    make_vault(tmp_path, "v", {"version": version, "source": "http://x.invalid",
                               "episodes": [], "streams": [], "clips": []})
    result = run("digest", "v")
    assert result.returncode != 0
    assert str(version) in result.stderr


# --------------------------------------------------------------------------
# `digest` Format-Aware Loading
# --------------------------------------------------------------------------

# Phrase: "| v1 | Single group: `Entries` | ..."
def test_v1_uses_a_single_entries_group(run, tmp_path):
    v1_vault(tmp_path, [v1_item("e1", title="Solo")])
    out = digest(run)
    assert "Entries" in out
    assert "Episodes" not in out and "Streams" not in out and "Clips" not in out


# Phrase: "| v2 | `Episodes`, `Streams`, `Clips` | ..."
def test_v2_groups_by_category(run, tmp_path):
    v2_vault(tmp_path,
             episodes=[item("e1", version=2, title="Ep")],
             streams=[item("s1", version=2, title="St")],
             clips=[item("c1", version=2, title="Cl")])
    out = digest(run)
    assert "Ep" in section_of(out, "Episodes")[-1]
    assert "St" in section_of(out, "Streams")[-1]
    assert "Cl" in section_of(out, "Clips")[-1]


# Phrase: "| v3 | `Episodes`, `Streams`, `Clips` | Full removal detection |"
def test_v3_groups_by_category(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Ep")],
             clips=[item("c1", title="Cl")])
    out = digest(run)
    assert "Ep" in "\n".join(section_of(out, "Episodes"))
    assert "Cl" in "\n".join(section_of(out, "Clips"))


# Phrase: "| v1 | ... | Not available (no `removed` field) | UNIX-epoch string
#          keys |"
# Context: a v1 catalog is read with epoch keys and reports no removals group.
def test_v1_has_no_removals_group(run, tmp_path):
    v1_vault(tmp_path, [v1_item("e1", title={E_OLD: "A", E_NEW: "B"})])
    out = digest(run)
    assert "Removal" not in out


# Phrase: "| v2 | ... | Not available (no `removed` field) | ISO 8601 string
#          keys |"
def test_v2_has_no_removals_group(run, tmp_path):
    v2_vault(tmp_path, episodes=[item("e1", version=2,
                                      title={T1: "A", T2: "B"})])
    out = digest(run)
    assert "Removal" not in out


# Phrase: "Removals ... | Not applicable; removals group is omitted entirely"
# Context: even a v2 entry that happens to carry a `removed` field is not
# treated as removable, because v2 has no removal detection.
def test_v2_ignores_a_stray_removed_field(run, tmp_path):
    stray = item("e1", version=2, title="Ghost")
    stray["removed"] = {T1: False, T2: True}
    v2_vault(tmp_path, episodes=[stray])
    out = digest(run)
    assert "Removal" not in out


# --------------------------------------------------------------------------
# `digest` Change Classification
# --------------------------------------------------------------------------

# Phrase: "Additions | Entry has only initial observations; no tracked field
#          has a second history entry"
def test_addition_is_an_entry_with_only_initial_observations(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Brand New")])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Additions") == ["Brand New"]


# Phrase: "Field updates | At least one tracked field has two or more history
#          entries and the latest two values differ"
def test_field_update_lists_the_changed_field(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title={T1: "Old", T2: "New"})])
    out = digest(run)
    updates = entry_lines(out, "Episodes", "Field updates")
    assert len(updates) == 1
    assert updates[0].startswith("New")
    assert "title" in updates[0]


# Phrase: "the latest two values differ"
# Context: two history entries with the same value are not a change.
def test_repeated_identical_value_is_not_a_field_update(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title={T1: "Same", T2: "Same"})])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Field updates") == []


# Phrase: "Field-update suffix | Changed field names in parentheses after
#          title"
def test_multiple_changed_fields_are_all_named(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title={T1: "A", T2: "B"},
                                      views={T1: 1, T2: 9})])
    line = entry_lines(run("digest", "v").stdout, "Episodes", "Field updates")[0]
    assert "(" in line and ")" in line
    suffix = line[line.index("(") + 1:line.rindex(")")]
    assert "title" in suffix and "views" in suffix


# Phrase: "Field updates | ... | Same rule applied to available tracked fields"
# Context: v1 has no `removed`, so only the source-tracked fields qualify.
def test_v1_field_update(run, tmp_path):
    v1_vault(tmp_path, [v1_item("e1", views={E_OLD: 1, E_NEW: 7})])
    line = entry_lines(digest(run), "Entries", "Field updates")[0]
    assert "views" in line


# Phrase: "Additions | ... | Same rule applied to available tracked fields"
def test_v1_addition(run, tmp_path):
    v1_vault(tmp_path, [v1_item("e1", title="Only Once")])
    assert entry_lines(digest(run), "Entries", "Additions") == ["Only Once"]


# Phrase: "Removals | Latest `removed` value is `true` and prior `removed`
#          value, if present, is `false`"
def test_removal_detected_from_removed_history(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Gone",
                                      removed={T1: False, T2: True})])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Removals") == ["Gone"]


# Phrase: "prior `removed` value, if present, is `false`"
# Context: a single `true` observation with no prior value still qualifies.
def test_removal_with_no_prior_value_qualifies(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Vanished",
                                      removed={T1: True})])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Removals") == ["Vanished"]


# Phrase: "Latest `removed` value is `true` and prior ... is `false`"
# Context: latest `false` is not a removal.
def test_present_entry_is_not_a_removal(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Here",
                                      removed={T1: False})])
    out = digest(run)
    assert "Removals" not in out


# --------------------------------------------------------------------------
# `digest` Group Precedence
# --------------------------------------------------------------------------

# Phrase: "Each entry may appear once." + "| `1` | Removals (v3 only) |"
# Context: a removed entry that also changed its title is reported only as a
# removal.
def test_removal_wins_over_field_update(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title={T1: "Old", T2: "New"},
                                      removed={T1: False, T2: True})])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Removals") == ["New"]
    assert entry_lines(out, "Episodes", "Field updates") == []
    assert out.count("New") == 1


# Phrase: "| `2` | Additions |" ranks above field updates.
# Context: an entry with only initial observations can never be a field
# update, so the ordering is visible in the emitted group order.
def test_additions_group_precedes_field_updates(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Fresh"),
                                 item("e2", title={T1: "A", T2: "B"})])
    out = digest(run)
    assert out.index("Additions") < out.index("Field updates")


# Phrase: "| `1` | Removals (v3 only) |" is the first group listed.
def test_removals_group_precedes_the_others(run, tmp_path):
    v3_vault(tmp_path, episodes=[
        item("e1", title="Fresh"),
        item("e2", title={T1: "A", T2: "B"}),
        item("e3", title="Dropped", removed={T1: False, T2: True}),
    ])
    out = digest(run)
    assert out.index("Removals") < out.index("Additions") < out.index("Field updates")


# Phrase: "Each entry may appear once."
def test_each_entry_appears_once(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title={T1: "A", T2: "Unique"},
                                      views={T1: 1, T2: 2})])
    out = digest(run)
    assert out.count("Unique") == 1


# --------------------------------------------------------------------------
# `digest` Current Value Resolution
# --------------------------------------------------------------------------

# Phrase: "| v1 | Value at the latest key by **numeric** comparison of
#          UNIX-epoch strings |"
def test_v1_current_value_uses_numeric_key_comparison(run, tmp_path):
    v1_vault(tmp_path, [v1_item("e1", title={E_OLD: "Older", E_NEW: "Newer"})])
    out = digest(run)
    line = entry_lines(out, "Entries", "Field updates")[0]
    assert line.startswith("Newer"), out


# Phrase: "v1 history ordering in digest | Numeric comparison of epoch-second
#          strings"
# Context: the *prior* value is the numerically second-latest key too.
def test_v1_prior_value_uses_numeric_key_comparison(run, tmp_path):
    v1_vault(tmp_path, [v1_item("e1", views={E_OLD: 5, E_NEW: 5})])
    out = digest(run)
    assert entry_lines(out, "Entries", "Field updates") == []


# Phrase: "| v2 | Value at the latest key by **lexicographic** comparison of
#          ISO 8601 strings |"
def test_v2_current_value_uses_lexicographic_key_comparison(run, tmp_path):
    # "2024-1-05..." sorts after "2024-02-01..." lexicographically.
    history = {"2024-02-01T00:00:00": "Second", "2024-1-05T00:00:00": "Last"}
    v2_vault(tmp_path, episodes=[item("e1", version=2, title=history)])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Field updates")[0].startswith("Last"), out


# Phrase: "| v3 | Value at the latest key by **lexicographic** comparison of
#          ISO 8601 strings |"
def test_v3_current_value_uses_latest_iso_key(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title={T1: "A", T2: "B", T3: "C"})])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Field updates")[0].startswith("C"), out


# Phrase: "Entry text | Current title from latest `title` history value"
def test_entry_text_is_the_current_title(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title={T1: "Working Title",
                                                   T2: "Final Title"})])
    out = digest(run)
    assert "Final Title" in out
    assert "Working Title" not in out


# --------------------------------------------------------------------------
# `digest` Source URL Resolution
# --------------------------------------------------------------------------

# Phrase: "| v1 | `https://media.example.com/channel/<source_id>` |"
def test_v1_source_url_is_derived_from_source_id(run, tmp_path):
    v1_vault(tmp_path, [v1_item("e1")], source_id="chan42")
    out = digest(run)
    assert V1_SOURCE_PREFIX + "chan42" in out


# Phrase: "| v2 | `source` field value |"
def test_v2_source_url_is_the_source_field(run, tmp_path):
    v2_vault(tmp_path, episodes=[item("e1", version=2)],
             source="http://v2.example.invalid/feed.json")
    assert "http://v2.example.invalid/feed.json" in digest(run)


# Phrase: "| v3 | `source` field value |"
def test_v3_source_url_is_the_source_field(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1")],
             source="http://v3.example.invalid/feed.json")
    assert "http://v3.example.invalid/feed.json" in digest(run)


# Phrase: "Source reference | The trailing line includes the resolved source
#          URL for the loaded vault version"
def test_source_url_is_on_the_trailing_line(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1")],
             source="http://tail.example.invalid/feed.json")
    out = digest(run).rstrip("\n")
    assert "http://tail.example.invalid/feed.json" in out.splitlines()[-1]


# Phrase: "Trailing line | Metadata about the digest run"
# Context: present even when there is nothing to report.
def test_trailing_line_present_with_no_changes(run, tmp_path):
    v3_vault(tmp_path, episodes=[], source="http://empty.example.invalid/f")
    out = digest(run).rstrip("\n")
    assert "http://empty.example.invalid/f" in out.splitlines()[-1]


# --------------------------------------------------------------------------
# `digest` Output Layout
# --------------------------------------------------------------------------

# Phrase: "Empty category | Omitted"
def test_empty_category_is_omitted(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Ep")])
    out = digest(run)
    assert "Episodes" in out
    assert "Streams" not in out
    assert "Clips" not in out


# Phrase: "Empty category | Omitted"
# Context: a category whose entries have no notable changes is also omitted.
def test_category_without_notable_changes_is_omitted(run, tmp_path):
    quiet = item("s1", title={T1: "Same", T2: "Same"})
    v3_vault(tmp_path, episodes=[item("e1", title="Ep")], streams=[quiet])
    out = digest(run)
    assert "Streams" not in out


# Phrase: "No notable changes anywhere | Indicate that no notable changes were
#          found"
def test_no_notable_changes_message(run, tmp_path):
    quiet = item("e1", title={T1: "Same", T2: "Same"})
    v3_vault(tmp_path, episodes=[quiet])
    out = digest(run)
    assert "no notable changes" in out.lower()


# Phrase: "No notable changes anywhere" — including a completely empty vault.
def test_empty_vault_reports_no_notable_changes(run, tmp_path):
    v3_vault(tmp_path)
    assert "no notable changes" in digest(run).lower()


# Phrase: "Reappearance after removal (v3 only) | Indicate reappearance
#          alongside any other changed fields"
def test_reappearance_is_indicated(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e1", title="Back",
                                      removed={T1: False, T2: True, T3: False})])
    out = digest(run)
    line = entry_lines(out, "Episodes", "Field updates")[0]
    assert line.startswith("Back")
    assert "reappear" in line.lower()


# Phrase: "Indicate reappearance alongside any other changed fields"
def test_reappearance_lists_other_changed_fields_too(run, tmp_path):
    v3_vault(tmp_path, episodes=[item(
        "e1", title={T1: "Old", T3: "New"},
        removed={T1: False, T2: True, T3: False})])
    line = entry_lines(digest(run), "Episodes", "Field updates")[0]
    assert line.startswith("New")
    assert "reappear" in line.lower()
    assert "title" in line


# Phrase: "Grouping within category | Changes grouped by type"
def test_changes_are_grouped_by_type_within_a_category(run, tmp_path):
    v3_vault(tmp_path, episodes=[
        item("e1", title="Added One"),
        item("e2", title={T1: "x", T2: "Updated One"}),
        item("e3", title="Added Two"),
    ])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Additions") == ["Added One", "Added Two"]
    assert entry_lines(out, "Episodes", "Field updates")[0].startswith("Updated One")


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------

# Phrase: "Digest category order | Deterministic",
#         "Digest group order | Deterministic",
#         "Digest entry order | Deterministic",
#         "Digest trailing line | Deterministic format"
def test_digest_output_is_byte_for_byte_repeatable(run, tmp_path):
    v3_vault(tmp_path, episodes=[
        item("e1", title="Fresh"),
        item("e2", title={T1: "A", T2: "B"}),
        item("e3", title="Dropped", removed={T1: False, T2: True}),
    ], streams=[item("s1", title="S")], clips=[item("c1", title="C")])
    first = digest(run)
    assert digest(run) == first


# Phrase: "Digest category order | Deterministic"
# Context: the category order does not follow the order the categories happen
# to appear in the catalog file.
def test_category_order_is_stable_across_catalog_key_order(run, tmp_path):
    episodes = [item("e1", title="E")]
    streams = [item("s1", title="S")]
    clips = [item("c1", title="C")]
    make_vault(tmp_path, "a", {"version": 3, "source": "http://x.invalid",
                               "episodes": episodes, "streams": streams,
                               "clips": clips})
    make_vault(tmp_path, "b", {"version": 3, "clips": clips,
                               "streams": streams, "episodes": episodes,
                               "source": "http://x.invalid"})

    order_a = [h for h in _headings(run("digest", "a").stdout)
               if h in ("Episodes", "Streams", "Clips")]
    order_b = [h for h in _headings(run("digest", "b").stdout)
               if h in ("Episodes", "Streams", "Clips")]
    assert order_a == order_b
    assert sorted(order_a) == ["Clips", "Episodes", "Streams"]


def _headings(text):
    return [line.strip().rstrip(":") for line in text.splitlines()
            if line and line == line.lstrip()]


# Phrase: "Digest entry order | Deterministic"
# Context: entries inside a group keep a single stable order regardless of how
# the vault is read.
def test_entry_order_within_group_is_deterministic(run, tmp_path):
    v3_vault(tmp_path, episodes=[item("e%d" % i, title="Title %d" % i)
                                 for i in range(1, 6)])
    out = digest(run)
    assert entry_lines(out, "Episodes", "Additions") == \
        entry_lines(run("digest", "v").stdout, "Episodes", "Additions")
