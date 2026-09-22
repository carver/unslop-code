"""Spec section: `sync` Update Rules."""

from conftest import entry_by_id, payload, read_catalog, run_cli, source_entry

TRACKED = ["title", "description", "views", "likes", "preview", "removed"]


def sync_with(vault, source, episodes=(), streams=(), clips=()):
    source.serve(payload(episodes, streams, clips))
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode == 0, result.stderr
    return read_catalog(vault)


def current(history):
    return history[max(history)]


# Update Rules: "First observation | Add entry to matching category".
def test_first_observation_adds_entry_to_matching_category(vault, source):
    catalog = sync_with(vault, source, streams=[source_entry("s1")])
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert catalog["episodes"] == [] and catalog["clips"] == []


# Update Rules: "First observation | ... create initial history entry for all
# six tracked fields".
def test_first_observation_creates_one_history_entry_per_tracked_field(vault, source):
    catalog = sync_with(vault, source, clips=[source_entry("c1")])
    entry = entry_by_id(catalog, "clips", "c1")
    for field in TRACKED:
        assert len(entry[field]) == 1, field


# Update Rules: "First observation | ... set `removed` to `false` at sync
# timestamp" — at the same timestamp as the other initial entries.
def test_first_observation_sets_removed_false_at_the_sync_timestamp(vault, source):
    catalog = sync_with(vault, source, episodes=[source_entry("e1")])
    entry = entry_by_id(catalog, "episodes", "e1")
    assert current(entry["removed"]) is False
    assert set(entry["removed"]) == set(entry["title"])


# Update Rules: "Existing entry, unchanged tracked value | No new history entry
# for that field".
def test_unchanged_entry_gains_no_history(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    catalog = sync_with(vault, source, episodes=[source_entry("e1")])

    entry = entry_by_id(catalog, "episodes", "e1")
    for field in TRACKED:
        assert len(entry[field]) == 1, field


# Update Rules: "Existing entry, changed tracked value | Append new history
# entry at sync timestamp" — only the changed field grows.
def test_changed_field_appends_and_others_do_not(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1", views=10)])
    catalog = sync_with(vault, source, episodes=[source_entry("e1", views=11)])

    entry = entry_by_id(catalog, "episodes", "e1")
    assert len(entry["views"]) == 2
    assert current(entry["views"]) == 11
    assert len(entry["title"]) == 1
    assert len(entry["preview"]) == 1


# Update Rules: "Existing entry, changed tracked value" — each of the five
# source-backed tracked fields is tracked independently.
def test_every_source_tracked_field_is_tracked(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    changed = source_entry(
        "e1", title="new", description="new", views=99, likes=None, preview="new"
    )
    catalog = sync_with(vault, source, episodes=[changed])

    entry = entry_by_id(catalog, "episodes", "e1")
    for field in ("title", "description", "views", "likes", "preview"):
        assert len(entry[field]) == 2, field


# Update Rules: "Entry absent from current source | Append `removed: true` at
# sync timestamp".
def test_absent_entry_is_marked_removed(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    catalog = sync_with(vault, source, episodes=[])

    entry = entry_by_id(catalog, "episodes", "e1")
    assert len(entry["removed"]) == 2
    assert current(entry["removed"]) is True


# Update Rules: "Removal handling | Never delete entry from `catalog.json`" —
# the entry and its whole history survive removal.
def test_removed_entry_is_never_deleted(vault, source):
    sync_with(vault, source, clips=[source_entry("c1", title="kept")])
    catalog = sync_with(vault, source, clips=[])

    entry = entry_by_id(catalog, "clips", "c1")
    assert current(entry["title"]) == "kept"


# Update Rules: an already-removed entry that stays absent gains no further
# history (see AMBIGUITIES T4).
def test_still_absent_entry_does_not_repeat_removed_true(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    sync_with(vault, source, episodes=[])
    catalog = sync_with(vault, source, episodes=[])

    assert len(entry_by_id(catalog, "episodes", "e1")["removed"]) == 2


# Update Rules: "Previously removed entry reappears | Append `removed: false` at
# sync timestamp".
def test_reappearing_entry_is_restored(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    sync_with(vault, source, episodes=[])
    catalog = sync_with(vault, source, episodes=[source_entry("e1")])

    entry = entry_by_id(catalog, "episodes", "e1")
    assert len(entry["removed"]) == 3
    assert current(entry["removed"]) is False


# Update Rules: a reappearing entry also records tracked values that changed
# while it was absent.
def test_reappearing_entry_records_changes_made_while_absent(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1", title="old")])
    sync_with(vault, source, episodes=[])
    catalog = sync_with(vault, source, episodes=[source_entry("e1", title="new")])

    entry = entry_by_id(catalog, "episodes", "e1")
    assert current(entry["title"]) == "new"
    assert len(entry["title"]) == 2


# Update Rules: a still-present entry is not affected by removals elsewhere.
def test_present_entry_stays_unremoved_when_a_sibling_disappears(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1"), source_entry("e2")])
    catalog = sync_with(vault, source, episodes=[source_entry("e1")])

    assert current(entry_by_id(catalog, "episodes", "e1")["removed"]) is False
    assert current(entry_by_id(catalog, "episodes", "e2")["removed"]) is True


# Update Rules: "Add entry to matching category" — the same id in another
# category is a separate entry (see AMBIGUITIES T5).
def test_same_id_in_two_categories_are_independent_entries(vault, source):
    sync_with(vault, source, episodes=[source_entry("x", title="ep")],
              clips=[source_entry("x", title="clip")])
    catalog = sync_with(vault, source, episodes=[source_entry("x", title="ep")])

    assert current(entry_by_id(catalog, "episodes", "x")["removed"]) is False
    assert current(entry_by_id(catalog, "clips", "x")["removed"]) is True
    assert current(entry_by_id(catalog, "clips", "x")["title"]) == "clip"


# `sync` Command: "Success effect | Update catalog with new, changed, removed,
# and restored entries" — all four cases in a single sync.
def test_one_sync_handles_new_changed_removed_and_restored(vault, source):
    sync_with(vault, source, episodes=[source_entry("keep"), source_entry("gone")])
    sync_with(vault, source, episodes=[source_entry("keep"), source_entry("gone")])
    sync_with(vault, source, episodes=[source_entry("keep")])  # "gone" disappears

    catalog = sync_with(
        vault,
        source,
        episodes=[source_entry("keep", views=42), source_entry("gone"), source_entry("fresh")],
    )

    assert current(entry_by_id(catalog, "episodes", "keep")["views"]) == 42
    assert current(entry_by_id(catalog, "episodes", "gone")["removed"]) is False
    assert len(entry_by_id(catalog, "episodes", "fresh")["title"]) == 1
