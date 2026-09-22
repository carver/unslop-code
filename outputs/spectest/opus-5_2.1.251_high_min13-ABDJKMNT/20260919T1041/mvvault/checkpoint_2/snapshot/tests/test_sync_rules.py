"""`sync` Update Rules and `likes` Null Semantics."""

import pytest

from conftest import current, read_catalog, source_entry

TRACKED = ["title", "description", "views", "likes", "preview", "removed"]


def sync(run_cli, source, episodes=(), streams=(), clips=()):
    source.payload = {
        "episodes": list(episodes),
        "streams": list(streams),
        "clips": list(clips),
    }
    result = run_cli("sync", "v")
    assert result.returncode == 0, result.stderr
    return result


def episode(vault, entry_id="a"):
    return next(e for e in read_catalog(vault)["episodes"] if e["id"] == entry_id)


# Spec: First observation | Add entry to matching category
def test_new_entries_land_in_their_category(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("e")], streams=[source_entry("s")], clips=[source_entry("c")])
    catalog = read_catalog(vault)
    assert [catalog["episodes"][0]["id"], catalog["streams"][0]["id"], catalog["clips"][0]["id"]] == ["e", "s", "c"]


# Spec: First observation | ... create initial history entry for all six tracked fields
def test_first_observation_creates_six_histories_with_one_key(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    entry = episode(vault)
    assert all(len(entry[field]) == 1 for field in TRACKED)


# Spec: First observation | ... set `removed` to `false` at sync timestamp
def test_first_observation_sets_removed_false_at_sync_timestamp(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    entry = episode(vault)
    assert current(entry["removed"]) is False
    assert max(entry["removed"]) == max(entry["title"])


# Spec: Existing entry, unchanged tracked value | No new history entry for that field
def test_unchanged_values_add_no_history(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    sync(run_cli, source, episodes=[source_entry("a")])
    entry = episode(vault)
    assert all(len(entry[field]) == 1 for field in TRACKED)


# Spec: Existing entry, changed tracked value | Append new history entry at sync timestamp
@pytest.mark.parametrize(
    "field,value",
    [("title", "new"), ("description", "new"), ("views", 99), ("likes", 7), ("preview", "z")],
)
def test_changed_value_appends_history(run_cli, vault, source, field, value):
    sync(run_cli, source, episodes=[source_entry("a")])
    sync(run_cli, source, episodes=[source_entry("a", **{field: value})])
    entry = episode(vault)
    assert len(entry[field]) == 2
    assert current(entry[field]) == value


# Spec: Existing entry, changed tracked value (only the changed field grows)
def test_only_changed_fields_grow(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    sync(run_cli, source, episodes=[source_entry("a", views=50)])
    entry = episode(vault)
    assert len(entry["views"]) == 2
    assert [len(entry[field]) for field in ("title", "description", "likes", "preview", "removed")] == [1, 1, 1, 1, 1]


# Spec: Existing entry ... static fields keep the original values (AMBIGUITIES T7)
def test_static_fields_are_not_rewritten(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", published="2024-01-01T00:00:00", width=100, height=50)])
    sync(run_cli, source, episodes=[source_entry("a", published="2025-01-01T00:00:00", width=999, height=999)])
    entry = episode(vault)
    assert (entry["published"], entry["width"], entry["height"]) == ("2024-01-01T00:00:00", 100, 50)


# Spec: Entry absent from current source | Append `removed: true` at sync timestamp
def test_absent_entry_is_marked_removed(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    sync(run_cli, source, episodes=[])
    entry = episode(vault)
    assert current(entry["removed"]) is True
    assert len(entry["removed"]) == 2


# Spec: Removal handling | Never delete entry from `catalog.json`
def test_removed_entry_stays_in_catalog(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    sync(run_cli, source, episodes=[])
    assert [e["id"] for e in read_catalog(vault)["episodes"]] == ["a"]


# Spec: Entry absent from current source ... unchanged tracked value adds nothing
def test_repeated_absence_adds_no_further_history(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    sync(run_cli, source, episodes=[])
    sync(run_cli, source, episodes=[])
    assert len(episode(vault)["removed"]) == 2


# Spec: Entry absent from current source (other tracked fields keep their values)
def test_removal_does_not_touch_other_fields(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", title="kept")])
    sync(run_cli, source, episodes=[])
    entry = episode(vault)
    assert current(entry["title"]) == "kept"
    assert len(entry["title"]) == 1


# Spec: Previously removed entry reappears | Append `removed: false` at sync timestamp
def test_reappearing_entry_is_restored(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    sync(run_cli, source, episodes=[])
    sync(run_cli, source, episodes=[source_entry("a")])
    entry = episode(vault)
    assert current(entry["removed"]) is False
    assert len(entry["removed"]) == 3


# Spec: Previously removed entry reappears (with changed values, both are recorded)
def test_reappearing_entry_records_changed_values(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", views=1)])
    sync(run_cli, source, episodes=[])
    sync(run_cli, source, episodes=[source_entry("a", views=2)])
    entry = episode(vault)
    assert current(entry["views"]) == 2
    assert current(entry["removed"]) is False


# Spec: `likes` change detection treats `null` as an ordinary value.
# A transition between `null` and a numeric value is a change
def test_numeric_to_null_is_a_change(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", likes=5)])
    sync(run_cli, source, episodes=[source_entry("a", likes=None)])
    entry = episode(vault)
    assert len(entry["likes"]) == 2 and current(entry["likes"]) is None


# Spec: A transition between `null` and a numeric value is a change
def test_null_to_numeric_is_a_change(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", likes=None)])
    sync(run_cli, source, episodes=[source_entry("a", likes=0)])
    entry = episode(vault)
    assert len(entry["likes"]) == 2 and current(entry["likes"]) == 0


# Spec: identical values produce no new history entry
def test_repeated_null_is_not_a_change(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", likes=None)])
    sync(run_cli, source, episodes=[source_entry("a", likes=None)])
    assert len(episode(vault)["likes"]) == 1


# Spec: identical values produce no new history entry (zero is not null)
def test_zero_likes_is_distinct_from_null(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", likes=0)])
    sync(run_cli, source, episodes=[source_entry("a", likes=0)])
    assert len(episode(vault)["likes"]) == 1


# Spec: Success effect | Update catalog with new, changed, removed, and restored entries
def test_one_sync_handles_new_changed_and_removed_together(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", views=1), source_entry("b")])
    sync(run_cli, source, episodes=[source_entry("a", views=2), source_entry("c")])
    catalog = read_catalog(vault)
    by_id = {entry["id"]: entry for entry in catalog["episodes"]}
    assert current(by_id["a"]["views"]) == 2
    assert current(by_id["b"]["removed"]) is True
    assert current(by_id["c"]["removed"]) is False


# Spec: First observation | Add entry to matching category (AMBIGUITIES T6:
# the same id in two categories is two independent entries)
def test_same_id_in_two_categories_is_independent(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("x", title="ep")], clips=[source_entry("x", title="clip")])
    catalog = read_catalog(vault)
    assert current(catalog["episodes"][0]["title"]) == "ep"
    assert current(catalog["clips"][0]["title"]) == "clip"
