"""Spec: `sync` Update Rules."""
import json

import pytest

from conftest import (TRACKED_FIELDS, current, find_entry, make_entry,
                      read_catalog, sorted_keys)


# Spec: "| First observation | Add entry to matching category; ... |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_first_observation_adds_to_matching_category(run, source, tmp_path, vault, category):
    source.serve(**{category: [make_entry(id="new1")]})
    assert run("sync", "vault").returncode == 0

    catalog = read_catalog(tmp_path)
    assert find_entry(catalog, category, "new1") is not None
    for other in ("episodes", "streams", "clips"):
        if other != category:
            assert catalog[other] == []


# Spec: "First observation | ... create initial history entry for all six
# tracked fields ..."
def test_first_observation_creates_one_entry_for_all_six_tracked_fields(
        run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    for field in TRACKED_FIELDS:
        assert len(entry[field]) == 1, field


# Spec: "First observation | ... set `removed` to `false` at sync timestamp"
def test_first_observation_sets_removed_false(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert list(entry["removed"].values()) == [False]


# Spec: "First observation | ... at sync timestamp" -- all six initial history
# entries share the one sync timestamp (see AMBIGUITIES T2).
def test_first_observation_uses_one_sync_timestamp(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    stamps = {next(iter(entry[f])) for f in TRACKED_FIELDS}
    assert len(stamps) == 1


# Spec: "| Existing entry, unchanged tracked value | No new history entry for
# that field |"
def test_unchanged_values_add_no_history(run, source, tmp_path, vault):
    payload = [make_entry(id="e1")]
    source.serve(episodes=payload)
    run("sync", "vault")
    source.serve(episodes=payload)
    run("sync", "vault")
    source.serve(episodes=payload)
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    for field in TRACKED_FIELDS:
        assert len(entry[field]) == 1, field


# Spec: "| Existing entry, changed tracked value | Append new history entry at
# sync timestamp |" -- for each of the five source-tracked fields.
@pytest.mark.parametrize("field,first,second", [
    ("title", "A", "B"),
    ("description", "one", "two"),
    ("views", 10, 11),
    ("likes", 1, 2),
    ("preview", "h1", "h2"),
])
def test_changed_value_appends_history(run, source, tmp_path, vault, field, first, second):
    source.serve(episodes=[make_entry(id="e1", **{field: first})])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", **{field: second})])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    keys = sorted_keys(entry[field])
    assert len(keys) == 2
    assert entry[field][keys[0]] == first
    assert entry[field][keys[1]] == second
    # Untouched fields keep a single entry.
    for other in TRACKED_FIELDS:
        if other != field:
            assert len(entry[other]) == 1, other


# Spec: "Existing entry, changed tracked value | Append ..." -- several fields
# changing in one sync.
def test_multiple_changed_fields_in_one_sync(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="A", views=1, preview="p1")])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", title="B", views=2, preview="p2")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert len(entry["title"]) == 2
    assert len(entry["views"]) == 2
    assert len(entry["preview"]) == 2
    assert len(entry["description"]) == 1
    stamps = {sorted_keys(entry[f])[-1] for f in ("title", "views", "preview")}
    assert len(stamps) == 1, "one sync uses one timestamp"


# Spec: "| Entry absent from current source | Append `removed: true` at sync
# timestamp |"
def test_absent_entry_is_marked_removed(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    source.serve(episodes=[])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    keys = sorted_keys(entry["removed"])
    assert len(keys) == 2
    assert entry["removed"][keys[0]] is False
    assert entry["removed"][keys[1]] is True
    assert current(entry["removed"]) is True


# Spec: "Entry absent from current source ..." -- the other tracked fields of a
# removed entry get no new history (their values are simply unknown).
def test_removal_does_not_touch_other_fields(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    source.serve(episodes=[])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    for field in ("title", "description", "views", "likes", "preview"):
        assert len(entry[field]) == 1, field


# Spec: "Entry absent from current source | Append `removed: true`" combined
# with "Existing entry, unchanged tracked value | No new history entry" -- the
# flag is appended on transition only (see AMBIGUITIES T12).
def test_repeated_absence_appends_once(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    source.serve(episodes=[])
    run("sync", "vault")
    run("sync", "vault")
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert len(entry["removed"]) == 2
    assert current(entry["removed"]) is True


# Spec: "| Previously removed entry reappears | Append `removed: false` at sync
# timestamp |"
def test_reappearing_entry_is_restored(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="A")])
    run("sync", "vault")
    source.serve(episodes=[])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", title="A")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    values = [entry["removed"][k] for k in sorted_keys(entry["removed"])]
    assert values == [False, True, False]
    assert current(entry["removed"]) is False


# Spec: "Previously removed entry reappears ..." -- a value that changed while
# the entry was away is recorded on the restoring sync.
def test_restored_entry_records_changed_values(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="A", views=1)])
    run("sync", "vault")
    source.serve(episodes=[])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", title="B", views=9)])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(entry["title"]) == "B"
    assert current(entry["views"]) == 9
    assert len(entry["title"]) == 2
    assert len(entry["views"]) == 2


# Spec: "Previously removed entry reappears" -- an entry that never left gets
# no extra `removed` entry.
def test_still_present_entry_gets_no_removed_entry(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", title="changed")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert len(entry["removed"]) == 1


# Spec: "| Removal handling | Never delete entry from `catalog.json` |"
def test_removed_entry_is_never_deleted(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")], clips=[make_entry(id="c1")])
    run("sync", "vault")
    source.serve()
    run("sync", "vault")
    run("sync", "vault")

    catalog = read_catalog(tmp_path)
    assert find_entry(catalog, "episodes", "e1") is not None
    assert find_entry(catalog, "clips", "c1") is not None


# Spec: "Removal handling | Never delete entry ..." -- the full history of a
# removed entry survives.
def test_removed_entry_keeps_history(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="A")])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", title="B")])
    run("sync", "vault")
    source.serve(episodes=[])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert [entry["title"][k] for k in sorted_keys(entry["title"])] == ["A", "B"]


# Spec: "| Success effect | Update catalog with new, changed, removed, and
# restored entries |" -- all four cases in a single sync.
def test_sync_handles_new_changed_removed_restored_together(run, source, tmp_path, vault):
    source.serve(episodes=[
        make_entry(id="stay", title="A"),
        make_entry(id="gone", title="G"),
        make_entry(id="back", title="B"),
    ])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="stay", title="A"),
                           make_entry(id="gone", title="G")])
    run("sync", "vault")  # `back` removed
    source.serve(episodes=[
        make_entry(id="stay", title="A2"),        # changed
        make_entry(id="back", title="B"),         # restored
        make_entry(id="fresh", title="F"),        # new
    ])                                            # `gone` removed
    assert run("sync", "vault").returncode == 0

    catalog = read_catalog(tmp_path)
    stay = find_entry(catalog, "episodes", "stay")
    gone = find_entry(catalog, "episodes", "gone")
    back = find_entry(catalog, "episodes", "back")
    fresh = find_entry(catalog, "episodes", "fresh")
    assert current(stay["title"]) == "A2"
    assert current(gone["removed"]) is True
    assert current(back["removed"]) is False
    assert len(back["removed"]) == 3
    assert current(fresh["removed"]) is False
    assert len(fresh["title"]) == 1


# Spec: "First observation | Add entry to matching category" -- the same id in
# two categories is tracked independently (see AMBIGUITIES T13).
def test_same_id_in_two_categories_is_independent(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="dup", title="ep")],
                 clips=[make_entry(id="dup", title="clip")])
    assert run("sync", "vault").returncode == 0

    catalog = read_catalog(tmp_path)
    assert current(find_entry(catalog, "episodes", "dup")["title"]) == "ep"
    assert current(find_entry(catalog, "clips", "dup")["title"]) == "clip"


# Spec: "| Static | `published` ... Original publication datetime |" -- static
# fields are captured once (see AMBIGUITIES T9).
def test_static_fields_are_not_rewritten(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", published="2024-05-01T12:00:00",
                                      width=1920, height=1080)])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", published="2030-01-01T00:00:00",
                                      width=640, height=480)])
    assert run("sync", "vault").returncode == 0

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert entry["published"] == "2024-05-01T12:00:00"
    assert entry["width"] == 1920
    assert entry["height"] == 1080
