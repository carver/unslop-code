"""Spec sections: `sync` Update Rules, `likes` Null Semantics."""

import pytest

from conftest import find_entry, latest, payload, read_catalog, source_entry, timestamps

TRACKED_FIELDS = ["title", "description", "views", "likes", "preview", "removed"]


# Spec: First observation | Add entry to matching category
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_first_observation_adds_to_matching_category(run, source, vault, category):
    source.serve(payload(**{category: [source_entry("x1")]}))
    run("sync", "vault")
    catalog = read_catalog(vault)
    assert [e["id"] for e in catalog[category]] == ["x1"]
    for other in set(catalog) - {"version", "source", category}:
        assert catalog[other] == []


# Spec: First observation | ... create initial history entry for all six tracked fields
def test_first_observation_creates_one_entry_per_tracked_field(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    entry = read_catalog(vault)["episodes"][0]
    for field in TRACKED_FIELDS:
        assert len(entry[field]) == 1, field


# Spec: First observation | ... set `removed` to `false` at sync timestamp
def test_first_observation_records_removed_false_at_sync_timestamp(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    entry = read_catalog(vault)["episodes"][0]
    assert list(entry["removed"].values()) == [False]
    assert set(entry["removed"]) == set(entry["title"])


# Spec: First observation ... (T1: the six initial entries share one sync timestamp)
def test_initial_history_entries_share_one_timestamp(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    entry = read_catalog(vault)["episodes"][0]
    stamps = {next(iter(entry[field])) for field in TRACKED_FIELDS}
    assert len(stamps) == 1


# Spec: Existing entry, unchanged tracked value | No new history entry for that field
def test_unchanged_values_add_no_history(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    run("sync", "vault")
    entry = read_catalog(vault)["episodes"][0]
    for field in TRACKED_FIELDS:
        assert len(entry[field]) == 1, field


# Spec: Existing entry, changed tracked value | Append new history entry at sync timestamp
@pytest.mark.parametrize(
    "field,new_value",
    [
        ("title", "Renamed"),
        ("description", "Rewritten"),
        ("views", 4242),
        ("likes", 77),
        ("preview", "hash-updated"),
    ],
)
def test_changed_value_appends_history(run, source, vault, field, new_value):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("e1", **{field: new_value})]))
    run("sync", "vault")

    entry = read_catalog(vault)["episodes"][0]
    assert len(entry[field]) == 2
    assert latest(entry[field]) == new_value
    for untouched in set(TRACKED_FIELDS) - {field}:
        assert len(entry[untouched]) == 1, untouched


# Spec: Existing entry, changed tracked value ... (static fields track the source)
def test_static_fields_follow_the_source_without_history(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", width=640, height=480)]))
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("e1", width=1920, height=1080)]))
    run("sync", "vault")

    entry = read_catalog(vault)["episodes"][0]
    assert entry["width"] == 1920
    assert entry["height"] == 1080


# Spec: Entry absent from current source | Append `removed: true` at sync timestamp
def test_absent_entry_is_marked_removed(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    source.serve(payload())
    run("sync", "vault")

    entry = read_catalog(vault)["episodes"][0]
    assert len(entry["removed"]) == 2
    assert latest(entry["removed"]) is True


# Spec: Entry absent from current source ... (no other field changes while absent)
def test_removal_touches_only_the_removed_history(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    source.serve(payload())
    run("sync", "vault")

    entry = read_catalog(vault)["episodes"][0]
    for field in set(TRACKED_FIELDS) - {"removed"}:
        assert len(entry[field]) == 1, field


# Spec: Existing entry, unchanged tracked value (staying absent is unchanged)
def test_staying_removed_adds_no_further_history(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    source.serve(payload())
    run("sync", "vault")
    run("sync", "vault")

    assert len(read_catalog(vault)["episodes"][0]["removed"]) == 2


# Spec: Previously removed entry reappears | Append `removed: false` at sync timestamp
def test_reappearing_entry_is_restored(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    source.serve(payload())
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")

    history = read_catalog(vault)["episodes"][0]["removed"]
    assert [history[k] for k in timestamps(history)] == [False, True, False]


# Spec: Previously removed entry reappears (T15: changes during absence also append)
def test_reappearing_entry_records_changed_fields(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", views=5)]))
    run("sync", "vault")
    source.serve(payload())
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("e1", views=500)]))
    run("sync", "vault")

    entry = read_catalog(vault)["episodes"][0]
    assert latest(entry["views"]) == 500
    assert len(entry["views"]) == 2
    assert latest(entry["removed"]) is False


# Spec: Removal handling | Never delete entry from `catalog.json`
def test_removed_entry_stays_in_catalog(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")], clips=[source_entry("c1")]))
    run("sync", "vault")
    source.serve(payload())
    run("sync", "vault")
    run("sync", "vault")

    catalog = read_catalog(vault)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Spec: Success effect | Update catalog with new, changed, removed, and restored entries
def test_one_sync_handles_all_four_cases(run, source, vault):
    gone = source_entry("gone", published="2024-04-04T00:00:00")
    stale = source_entry("stale", published="2024-03-03T00:00:00")
    back = source_entry("back", published="2024-02-02T00:00:00")

    source.serve(payload(episodes=[gone, stale, back]))
    run("sync", "vault")
    source.serve(payload(episodes=[gone, stale]))
    run("sync", "vault")

    fresh = source_entry("fresh", published="2024-05-05T00:00:00")
    source.serve(
        payload(episodes=[fresh, source_entry("stale", published="2024-03-03T00:00:00", title="new"), back])
    )
    run("sync", "vault")

    catalog = read_catalog(vault)
    assert latest(find_entry(catalog, "episodes", "fresh")["removed"]) is False
    assert latest(find_entry(catalog, "episodes", "stale")["title"]) == "new"
    assert latest(find_entry(catalog, "episodes", "gone")["removed"]) is True
    assert latest(find_entry(catalog, "episodes", "back")["removed"]) is False


# Spec: `likes` change detection treats `null` as an ordinary value.
def test_null_to_number_is_a_change(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", likes=None)]))
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("e1", likes=9)]))
    run("sync", "vault")

    history = read_catalog(vault)["episodes"][0]["likes"]
    assert [history[k] for k in timestamps(history)] == [None, 9]


# Spec: A transition between `null` and a numeric value is a change.
def test_number_to_null_is_a_change(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", likes=9)]))
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("e1", likes=None)]))
    run("sync", "vault")

    history = read_catalog(vault)["episodes"][0]["likes"]
    assert [history[k] for k in timestamps(history)] == [9, None]


# Spec: ... identical values produce no new history entry.
def test_repeated_null_likes_add_no_history(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", likes=None)]))
    run("sync", "vault")
    run("sync", "vault")
    assert len(read_catalog(vault)["episodes"][0]["likes"]) == 1


# Spec: ... identical values produce no new history entry.
def test_repeated_numeric_likes_add_no_history(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", likes=0)]))
    run("sync", "vault")
    run("sync", "vault")
    assert len(read_catalog(vault)["episodes"][0]["likes"]) == 1


# Spec: First observation ... (T4: identity is per category)
def test_same_id_in_two_categories_is_two_entries(run, source, vault):
    source.serve(payload(episodes=[source_entry("dup", title="ep")], clips=[source_entry("dup", title="clip")]))
    run("sync", "vault")

    catalog = read_catalog(vault)
    assert latest(find_entry(catalog, "episodes", "dup")["title"]) == "ep"
    assert latest(find_entry(catalog, "clips", "dup")["title"]) == "clip"


# Spec: Entry absent from current source (T4: absence is judged per category)
def test_moving_an_id_between_categories(run, source, vault):
    source.serve(payload(episodes=[source_entry("m1")]))
    run("sync", "vault")
    source.serve(payload(clips=[source_entry("m1")]))
    run("sync", "vault")

    catalog = read_catalog(vault)
    assert latest(find_entry(catalog, "episodes", "m1")["removed"]) is True
    assert latest(find_entry(catalog, "clips", "m1")["removed"]) is False


# Spec: `id` | Unique identifier (T12: last occurrence wins on duplicates)
def test_duplicate_ids_in_one_category_collapse(run, source, vault):
    source.serve(
        payload(episodes=[source_entry("d1", title="earlier"), source_entry("d1", title="later")])
    )
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(vault)
    assert len(catalog["episodes"]) == 1
    assert latest(catalog["episodes"][0]["title"]) == "later"
