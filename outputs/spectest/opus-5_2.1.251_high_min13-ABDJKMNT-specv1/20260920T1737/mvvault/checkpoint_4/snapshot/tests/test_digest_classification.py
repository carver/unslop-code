"""`digest` change classification and group precedence."""

from conftest import ISO_KEY, v3_catalog, v3_entry, write_vault

LATER = "2024-07-01T10:00:00"
LATEST = "2024-08-01T10:00:00"


def digest_of(tmp_path, run_cli, *entries):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=list(entries)))
    result = run_cli("digest", "demo")
    assert result.returncode == 0, result.stderr
    return result.stdout


# Spec: "| Additions | Entry has only initial observations; no tracked field has
# a second history entry |".
def test_entry_with_only_initial_observations_is_an_addition(tmp_path, run_cli):
    stdout = digest_of(tmp_path, run_cli, v3_entry("e1"))

    assert "Added" in stdout
    assert "title-e1" in stdout


# Spec: "| Field updates | At least one tracked field has two or more history
# entries and the latest two values differ |".
def test_changed_tracked_field_is_a_field_update(tmp_path, run_cli):
    stdout = digest_of(tmp_path, run_cli, v3_entry("e1", views={ISO_KEY: 10, LATER: 20}))

    assert "Updated" in stdout
    assert "views" in stdout


# Spec: "| Field-update suffix | Changed field names in parentheses after title |".
def test_changed_field_names_follow_the_title_in_parentheses(tmp_path, run_cli):
    entry = v3_entry("e1", title={ISO_KEY: "old", LATER: "new"}, likes={ISO_KEY: 1, LATER: 2})
    stdout = digest_of(tmp_path, run_cli, entry)

    line = [text for text in stdout.splitlines() if "new" in text][0]
    assert "(" in line and ")" in line
    assert "title" in line and "likes" in line


# Spec: "| Field updates | At least one tracked field has two or more history
# entries and the latest two values differ |" -- a repeated value does not count.
def test_history_whose_latest_two_values_match_is_not_an_update(tmp_path, run_cli):
    entry = v3_entry("e1", views={ISO_KEY: 10, LATER: 20, LATEST: 20})
    stdout = digest_of(tmp_path, run_cli, entry)

    assert "Updated" not in stdout


# Spec: "| Removals | Latest `removed` value is `true` and prior `removed`
# value, if present, is `false` |".
def test_entry_marked_removed_is_a_removal(tmp_path, run_cli):
    entry = v3_entry("e1", removed={ISO_KEY: False, LATER: True})
    stdout = digest_of(tmp_path, run_cli, entry)

    assert "Removed" in stdout
    assert "title-e1" in stdout


# Spec: "| Priority | `1` | Removals (v3 only) |" over "| `3` | Field updates |"
# and "Each entry may appear once."
def test_removal_takes_precedence_over_field_updates(tmp_path, run_cli):
    entry = v3_entry(
        "e1",
        title={ISO_KEY: "old", LATER: "new"},
        removed={ISO_KEY: False, LATER: True},
    )
    stdout = digest_of(tmp_path, run_cli, entry)

    assert stdout.count("new") == 1
    assert "Updated" not in stdout


# Spec: "| Priority | `2` | Additions |" over "| `3` | Field updates |" -- an
# entry with only initial observations can never also be an update.
def test_addition_and_update_are_mutually_exclusive(tmp_path, run_cli):
    stdout = digest_of(tmp_path, run_cli, v3_entry("e1"), v3_entry("e2", likes={ISO_KEY: 1, LATER: 5}))

    assert stdout.count("title-e1") == 1
    assert stdout.count("title-e2") == 1


# Spec: "| Reappearance after removal (v3 only) | Indicate reappearance
# alongside any other changed fields |".
def test_reappearance_is_indicated_with_other_changed_fields(tmp_path, run_cli):
    entry = v3_entry(
        "e1",
        title={ISO_KEY: "old", LATER: "new"},
        removed={ISO_KEY: False, LATER: True, LATEST: False},
    )
    stdout = digest_of(tmp_path, run_cli, entry)

    line = [text for text in stdout.splitlines() if "new" in text][0]
    assert "reappear" in line.lower()
    assert "title" in line
    assert "Removed" not in stdout


# Spec: "| Removals | Latest `removed` value is `true` and prior `removed`
# value, if present, is `false` |" -- an entry that was already removed before
# the latest observation does not qualify again.
def test_entry_that_stays_removed_is_not_reported_again(tmp_path, run_cli):
    entry = v3_entry("e1", removed={ISO_KEY: False, LATER: True, LATEST: True})
    stdout = digest_of(tmp_path, run_cli, entry)

    assert "title-e1" not in stdout


# Spec: "| Removals | Latest `removed` value is `true` and prior `removed`
# value, if present, is `false` |" -- with no prior value the condition on it
# does not apply, so the entry is still a removal.
def test_removed_without_a_prior_value_is_a_removal(tmp_path, run_cli):
    stdout = digest_of(tmp_path, run_cli, v3_entry("e1", removed={ISO_KEY: True}))

    assert "Removed" in stdout
    assert "title-e1" in stdout
