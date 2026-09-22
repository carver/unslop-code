"""Spec: `digest` Change Classification and `digest` Group Precedence."""
import pytest

from digest_helpers import (K1, K2, K3, v1, v2, v3, v3_entry, legacy_entry, v1_entry,
                            sections, entry_titles)

ADDED = "Added"
REMOVED = "Removed"
UPDATED = "Updated"


# Spec: "| Additions | Entry has only initial observations; no tracked field
# has a second history entry |"
def test_addition_is_an_entry_with_only_initial_observations(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Fresh")]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Episodes", ADDED) == ["Fresh"]


# Spec: "Additions | ... no tracked field has a second history entry" -- one
# second history entry disqualifies the entry from Additions.
def test_second_history_entry_disqualifies_addition(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="A",
                                     views={K1: 1, K2: 2})]))
    groups = sections(run("digest", "vault").stdout).get("Episodes", {})
    assert ADDED not in groups


# Spec: "Additions | ... no tracked field has a second history entry" -- in v3
# the `removed` field is tracked too, so a second `removed` observation also
# disqualifies.
def test_second_removed_observation_disqualifies_addition(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     removed={K1: False, K2: False})]))
    groups = sections(run("digest", "vault").stdout).get("Episodes", {})
    assert ADDED not in groups


# Spec: "| Field updates | At least one tracked field has two or more history
# entries and the latest two values differ |"
def test_field_update_when_latest_two_values_differ(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "Old", K2: "New"})]))
    assert entry_titles(run("digest", "vault").stdout, "Episodes", UPDATED) \
        == ["New (title)"]


# Spec: "Field updates | ... the latest two values differ" -- equal latest two
# values are not an update, so the entry appears in no group.
def test_equal_latest_two_values_is_not_an_update(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "Same", K2: "Same"})]))
    out = run("digest", "vault").stdout
    assert sections(out) == {}


# Spec: "Field updates | At least one tracked field has two or more history
# entries and the latest two values differ" -- only the *latest two* matter.
def test_only_the_latest_two_values_are_compared(run, make_vault):
    make_vault(v3(episodes=[
        v3_entry(id="e1", title={K1: "A", K2: "B", K3: "B"})]))
    out = run("digest", "vault").stdout
    assert sections(out) == {}


# Spec: "| Field-update suffix | Changed field names in parentheses after
# title |" -- several fields at once.
def test_multiple_changed_fields_listed(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "T1", K2: "T2"},
                                     views={K1: 1, K2: 5})]))
    line = entry_titles(run("digest", "vault").stdout, "Episodes", UPDATED)[0]
    assert line.startswith("T2 (")
    assert "title" in line and "views" in line


# Spec: "Field updates | ..." -- a field whose history did not change is not
# listed in the suffix.
def test_unchanged_field_not_listed_in_suffix(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "T1", K2: "T2"},
                                     views={K1: 3, K2: 3})]))
    line = entry_titles(run("digest", "vault").stdout, "Episodes", UPDATED)[0]
    assert "views" not in line
    assert "title" in line


# Spec: "| Removals | Latest `removed` value is `true` and prior `removed`
# value, if present, is `false` |"
def test_removal_detected(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Gone",
                                     removed={K1: False, K2: True})]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Episodes", REMOVED) == ["Gone"]


# Spec: "Removals | Latest `removed` value is `true` and prior `removed` value,
# if present, is `false` |" -- "if present" covers a lone `true` observation.
def test_removal_with_no_prior_value(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Gone",
                                     removed={K1: True})]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Episodes", REMOVED) == ["Gone"]


# Spec: "Removals | Latest `removed` value is `true` and prior ... is `false`"
# -- a repeated `true` (prior value already `true`) is not a fresh removal.
def test_repeated_removal_is_not_a_removal(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Gone",
                                     removed={K1: True, K2: True})]))
    groups = sections(run("digest", "vault").stdout).get("Episodes", {})
    assert REMOVED not in groups


# Spec: "Removals | Latest `removed` value is `true` ..." -- latest `false`
# is not a removal.
def test_latest_removed_false_is_not_a_removal(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Here",
                                     removed={K1: True, K2: False})]))
    groups = sections(run("digest", "vault").stdout).get("Episodes", {})
    assert REMOVED not in groups


# Spec: "| Priority | `1` | Removals (v3 only) |" + "Each entry may appear
# once." -- a removal that also changed other fields is reported as a removal.
def test_removal_takes_precedence_over_field_updates(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "Old", K2: "New"},
                                     removed={K1: False, K2: True})]))
    groups = sections(run("digest", "vault").stdout)["Episodes"]
    assert groups[REMOVED] == ["New"]
    assert UPDATED not in groups


# Spec: "| Priority | `2` | Additions |" over "`3` | Field updates" -- by
# construction an addition has no second history entry, so the two never
# collide; an addition is reported under Additions.
def test_addition_reported_as_addition(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="New One")]))
    groups = sections(run("digest", "vault").stdout)["Episodes"]
    assert groups[ADDED] == ["New One"]
    assert UPDATED not in groups


# Spec: "Each entry may appear once." -- across the whole digest.
def test_entry_appears_at_most_once(run, make_vault):
    make_vault(v3(episodes=[
        v3_entry(id="e1", title={K1: "A", K2: "B"}, removed={K1: False, K2: True}),
        v3_entry(id="e2", title="Brand New"),
        v3_entry(id="e3", title={K1: "C", K2: "D"}),
    ]))
    out = run("digest", "vault").stdout
    flat = [text for groups in sections(out).values()
            for lines in groups.values() for text in lines]
    assert len(flat) == 3


# Spec: "| Reappearance after removal (v3 only) | Indicate reappearance
# alongside any other changed fields |"
def test_reappearance_is_indicated(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Back",
                                     removed={K1: True, K2: False})]))
    line = entry_titles(run("digest", "vault").stdout, "Episodes", UPDATED)[0]
    assert line.startswith("Back (")
    assert "reappear" in line.lower()


# Spec: "Indicate reappearance alongside any other changed fields"
def test_reappearance_lists_other_changed_fields_too(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "Old", K2: "Back"},
                                     removed={K1: True, K2: False})]))
    line = entry_titles(run("digest", "vault").stdout, "Episodes", UPDATED)[0]
    assert line.startswith("Back (")
    assert "reappear" in line.lower()
    assert "title" in line


# Spec: "| Additions | ... | Same rule applied to available tracked fields |"
# (v2) -- v2 has no `removed`, so a single-observation entry is an addition.
def test_v2_addition(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1", title="Fresh V2")]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Episodes", ADDED) == ["Fresh V2"]


# Spec: "| Field updates | ... | Same rule applied to available tracked
# fields |" (v2).
def test_v2_field_update(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1",
                                         title={K1: "Old", K2: "New V2"})]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Episodes", UPDATED) == ["New V2 (title)"]


# Spec: "| Removals | ... | Not applicable; removals group is omitted
# entirely |" -- v2 has no `removed` field at all.
def test_v2_has_no_removals_group(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    groups = sections(run("digest", "vault").stdout)["Episodes"]
    assert REMOVED not in groups


# Spec: "| v2 | ... | Removal Detection | Not available (no `removed` field) |"
# -- even if a v2 entry somehow carried `removed`, it is not a tracked field
# for a v2 catalog, so the entry is still just an addition.
def test_v2_removed_field_is_ignored(run, make_vault):
    entry = legacy_entry(id="e1", title="Still Added")
    entry["removed"] = {K1: False, K2: True}
    make_vault(v2(episodes=[entry]))
    groups = sections(run("digest", "vault").stdout)["Episodes"]
    assert REMOVED not in groups
    assert groups[ADDED] == ["Still Added"]


# Spec: "| v1 | Single group: `Entries` | Not available (no `removed` field) |"
def test_v1_has_no_removals_group(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    groups = sections(run("digest", "vault").stdout)["Entries"]
    assert REMOVED not in groups


# Spec: "| Additions | ... | Same rule applied to available tracked fields |"
# (v1).
def test_v1_addition(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title="Fresh V1")]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Entries", ADDED) == ["Fresh V1"]


# Spec: "| No notable changes anywhere | Indicate that no notable changes were
# found |"
def test_no_notable_changes_message(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title={K1: "S", K2: "S"})]))
    out = run("digest", "vault").stdout
    assert sections(out) == {}
    assert "no notable changes" in out.lower()


# Spec: "No notable changes anywhere | Indicate that no notable changes were
# found" -- an entirely empty vault also qualifies.
def test_empty_vault_reports_no_notable_changes(run, make_vault):
    make_vault(v3())
    out = run("digest", "vault").stdout
    assert "no notable changes" in out.lower()


# Spec: "No notable changes anywhere ..." -- the message is absent when there
# is at least one change.
def test_no_notable_changes_message_absent_when_changes_exist(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    out = run("digest", "vault").stdout
    assert "no notable changes" not in out.lower()
