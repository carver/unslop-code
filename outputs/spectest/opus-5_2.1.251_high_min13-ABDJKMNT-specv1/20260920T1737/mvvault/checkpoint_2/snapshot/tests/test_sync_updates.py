"""Spec section: `sync` Update Rules / `likes` Null Semantics / history growth."""

from conftest import current, find_entry, history_order, read_catalog, source_entry


def sync(run_cli):
    result = run_cli("sync", "demo")
    assert result.returncode == 0, result.stderr
    return result


# Phrase: "First observation | Add entry to matching category"
def test_first_observation_adds_entry_to_matching_category(run_cli, source, vault):
    source.serve(streams=[source_entry("s1")])
    sync(run_cli)
    catalog = read_catalog(vault)
    assert [entry["id"] for entry in catalog["streams"]] == ["s1"]
    assert catalog["episodes"] == [] and catalog["clips"] == []


# Phrase: "create initial history entry for all six tracked fields"
def test_first_observation_creates_single_history_entry_per_tracked_field(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)
    entry = find_entry(read_catalog(vault), "episodes", "e1")
    for field in ("title", "description", "views", "likes", "preview", "removed"):
        assert len(entry[field]) == 1, field


# Phrase: "set `removed` to `false` at sync timestamp"
def test_first_observation_marks_entry_not_removed_at_sync_timestamp(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)
    entry = find_entry(read_catalog(vault), "episodes", "e1")
    assert list(entry["removed"].values()) == [False]
    assert list(entry["removed"]) == list(entry["title"])


# Phrase: "Existing entry, unchanged tracked value | No new history entry for that field"
def test_unchanged_values_do_not_grow_history(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)
    sync(run_cli)
    sync(run_cli)
    entry = find_entry(read_catalog(vault), "episodes", "e1")
    for field in ("title", "description", "views", "likes", "preview", "removed"):
        assert len(entry[field]) == 1, field


# Phrase: "Existing entry, changed tracked value | Append new history entry at sync timestamp"
def test_changed_value_appends_history_entry(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", title="first")])
    sync(run_cli)
    source.serve(episodes=[source_entry("e1", title="second")])
    sync(run_cli)

    title = find_entry(read_catalog(vault), "episodes", "e1")["title"]
    assert len(title) == 2
    assert [title[key] for key in history_order(title)] == ["first", "second"]


# Phrase: "Append new history entry at sync timestamp" - only the changed field grows
def test_only_changed_fields_append(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", views=10)])
    sync(run_cli)
    source.serve(episodes=[source_entry("e1", views=11)])
    sync(run_cli)

    entry = find_entry(read_catalog(vault), "episodes", "e1")
    assert len(entry["views"]) == 2
    assert len(entry["title"]) == 1
    assert len(entry["description"]) == 1
    assert len(entry["preview"]) == 1
    assert len(entry["likes"]) == 1
    assert len(entry["removed"]) == 1


# Phrase: "Entry absent from current source | Append `removed: true` at sync timestamp"
def test_absent_entry_is_marked_removed(run_cli, source, vault):
    source.serve(clips=[source_entry("c1")])
    sync(run_cli)
    source.serve(clips=[])
    sync(run_cli)

    removed = find_entry(read_catalog(vault), "clips", "c1")["removed"]
    assert [removed[key] for key in history_order(removed)] == [False, True]


# Phrase: "Removal handling | Never delete entry from `catalog.json`"
def test_removed_entry_is_retained(run_cli, source, vault):
    source.serve(clips=[source_entry("c1", title="kept")])
    sync(run_cli)
    source.serve(clips=[])
    sync(run_cli)

    entry = find_entry(read_catalog(vault), "clips", "c1")
    assert current(entry["title"]) == "kept"


# Phrase: "Entry absent from current source" - a still-absent entry adds nothing further
def test_repeated_absence_does_not_append(run_cli, source, vault):
    source.serve(clips=[source_entry("c1")])
    sync(run_cli)
    source.serve(clips=[])
    sync(run_cli)
    sync(run_cli)
    assert len(find_entry(read_catalog(vault), "clips", "c1")["removed"]) == 2


# Phrase: "Previously removed entry reappears | Append `removed: false` at sync timestamp"
def test_reappearing_entry_is_restored(run_cli, source, vault):
    source.serve(clips=[source_entry("c1")])
    sync(run_cli)
    source.serve(clips=[])
    sync(run_cli)
    source.serve(clips=[source_entry("c1")])
    sync(run_cli)

    removed = find_entry(read_catalog(vault), "clips", "c1")["removed"]
    assert [removed[key] for key in history_order(removed)] == [False, True, False]


# Phrase: "Previously removed entry reappears" - tracked changes while absent are recorded on return
def test_restored_entry_records_changed_values(run_cli, source, vault):
    source.serve(clips=[source_entry("c1", views=1)])
    sync(run_cli)
    source.serve(clips=[])
    sync(run_cli)
    source.serve(clips=[source_entry("c1", views=9)])
    sync(run_cli)

    entry = find_entry(read_catalog(vault), "clips", "c1")
    assert current(entry["views"]) == 9
    assert len(entry["views"]) == 2


# Phrase: "`likes` change detection treats `null` as an ordinary value."
def test_likes_null_to_number_is_a_change(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", likes=None)])
    sync(run_cli)
    source.serve(episodes=[source_entry("e1", likes=4)])
    sync(run_cli)

    likes = find_entry(read_catalog(vault), "episodes", "e1")["likes"]
    assert [likes[key] for key in history_order(likes)] == [None, 4]


# Phrase: "A transition between `null` and a numeric value is a change"
def test_likes_number_to_null_is_a_change(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", likes=4)])
    sync(run_cli)
    source.serve(episodes=[source_entry("e1", likes=None)])
    sync(run_cli)

    likes = find_entry(read_catalog(vault), "episodes", "e1")["likes"]
    assert [likes[key] for key in history_order(likes)] == [4, None]


# Phrase: "identical values produce no new history entry"
def test_repeated_null_likes_do_not_append(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", likes=None)])
    sync(run_cli)
    sync(run_cli)
    assert len(find_entry(read_catalog(vault), "episodes", "e1")["likes"]) == 1


# Phrase: "Update catalog with new, changed, removed, and restored entries" - all in one sync
def test_single_sync_handles_new_changed_and_removed(run_cli, source, vault):
    source.serve(episodes=[source_entry("keep", title="old"), source_entry("drop")])
    sync(run_cli)
    source.serve(episodes=[source_entry("keep", title="new"), source_entry("fresh")])
    sync(run_cli)

    catalog = read_catalog(vault)
    assert current(find_entry(catalog, "episodes", "keep")["title"]) == "new"
    assert current(find_entry(catalog, "episodes", "drop")["removed"]) is True
    assert current(find_entry(catalog, "episodes", "fresh")["removed"]) is False


# Phrase: "Add entry to matching category" - ids are matched within their category (see AMBIGUITIES T9)
def test_same_id_in_two_categories_is_two_entries(run_cli, source, vault):
    source.serve(episodes=[source_entry("x", title="ep")], clips=[source_entry("x", title="clip")])
    sync(run_cli)
    catalog = read_catalog(vault)
    assert current(find_entry(catalog, "episodes", "x")["title"]) == "ep"
    assert current(find_entry(catalog, "clips", "x")["title"]) == "clip"
