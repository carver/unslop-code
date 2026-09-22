"""Spec sections: `tracked field` History Format / `likes` Null Semantics."""

import json
import re

from conftest import entry_by_id, payload, read_catalog, run_cli, source_entry

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def sync_with(vault, source, entries, category="episodes"):
    source.serve(payload(**{category: entries}))
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode == 0, result.stderr
    return read_catalog(vault)


def current(history):
    """Value at the latest datetime key."""
    return history[max(history)]


# History Format: "Key format | ISO 8601 datetime string" — and Determinism:
# "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix".
def test_history_keys_use_the_documented_datetime_text(vault, source):
    catalog = sync_with(vault, source, [source_entry("e1")])
    entry = entry_by_id(catalog, "episodes", "e1")
    for field in ("title", "description", "views", "likes", "preview", "removed"):
        for key in entry[field]:
            assert TIMESTAMP.match(key), (field, key)


# History Format: "Value selection | Current value = value at latest datetime
# key" — after two changes the newest key carries the newest value.
def test_current_value_is_the_value_at_the_latest_key(vault, source):
    sync_with(vault, source, [source_entry("e1", title="first")])
    sync_with(vault, source, [source_entry("e1", title="second")])
    catalog = sync_with(vault, source, [source_entry("e1", title="third")])

    history = entry_by_id(catalog, "episodes", "e1")["title"]
    assert len(history) == 3
    assert current(history) == "third"


# History Format: "Comparison order | Chronological timestamp order" — change
# detection compares against the chronologically latest value, so returning to
# an older value is itself a change.
def test_reverting_to_a_previous_value_appends_a_new_entry(vault, source):
    sync_with(vault, source, [source_entry("e1", title="A")])
    sync_with(vault, source, [source_entry("e1", title="B")])
    catalog = sync_with(vault, source, [source_entry("e1", title="A")])

    history = entry_by_id(catalog, "episodes", "e1")["title"]
    assert len(history) == 3
    assert current(history) == "A"


# History Format: "Collision handling | When a new history entry would reuse an
# existing or non-newer second, advance to a strictly later second before
# writing" — back-to-back syncs in the same second still get distinct keys.
def test_rapid_syncs_never_reuse_a_key(vault, source):
    sync_with(vault, source, [source_entry("e1", views=1)])
    sync_with(vault, source, [source_entry("e1", views=2)])
    catalog = sync_with(vault, source, [source_entry("e1", views=3)])

    history = entry_by_id(catalog, "episodes", "e1")["views"]
    assert len(history) == 3
    assert current(history) == 3


# Collision handling: a pre-existing future timestamp forces the next append to
# a strictly later second.
def test_append_advances_past_a_future_existing_key(vault, source):
    sync_with(vault, source, [source_entry("e1", views=1)])

    catalog = read_catalog(vault)
    entry = entry_by_id(catalog, "episodes", "e1")
    future = "2999-01-01T00:00:00"
    entry["views"] = {future: 1}
    (vault / "catalog.json").write_text(json.dumps(catalog))

    catalog = sync_with(vault, source, [source_entry("e1", views=2)])
    history = entry_by_id(catalog, "episodes", "e1")["views"]
    assert max(history) > future
    assert current(history) == 2


# History Format: "JSON object key order | Not part of the contract" — history
# is interpreted by key value, so a file whose keys are stored out of order is
# still read chronologically.
def test_history_is_read_by_key_not_by_file_order(vault, source):
    sync_with(vault, source, [source_entry("e1", title="A")])
    catalog = read_catalog(vault)
    entry = entry_by_id(catalog, "episodes", "e1")
    entry["title"] = {"2020-01-02T00:00:00": "newest", "2020-01-01T00:00:00": "oldest"}
    (vault / "catalog.json").write_text(json.dumps(catalog))

    # Re-syncing "newest" is not a change; re-syncing "oldest" is.
    catalog = sync_with(vault, source, [source_entry("e1", title="newest")])
    assert len(entry_by_id(catalog, "episodes", "e1")["title"]) == 2


# Null Semantics: "A transition between `null` and a numeric value is a change".
def test_null_to_number_is_a_change(vault, source):
    sync_with(vault, source, [source_entry("e1", likes=None)])
    catalog = sync_with(vault, source, [source_entry("e1", likes=4)])

    history = entry_by_id(catalog, "episodes", "e1")["likes"]
    assert len(history) == 2
    assert current(history) == 4


# Null Semantics: the reverse transition is a change too.
def test_number_to_null_is_a_change(vault, source):
    sync_with(vault, source, [source_entry("e1", likes=4)])
    catalog = sync_with(vault, source, [source_entry("e1", likes=None)])

    history = entry_by_id(catalog, "episodes", "e1")["likes"]
    assert len(history) == 2
    assert current(history) is None


# Null Semantics: "identical values produce no new history entry" — including
# null repeated.
def test_repeated_null_likes_appends_nothing(vault, source):
    sync_with(vault, source, [source_entry("e1", likes=None)])
    catalog = sync_with(vault, source, [source_entry("e1", likes=None)])

    assert len(entry_by_id(catalog, "episodes", "e1")["likes"]) == 1


# Null Semantics: "`likes` change detection treats `null` as an ordinary value"
# — zero and null are distinct values.
def test_zero_and_null_likes_are_distinct(vault, source):
    sync_with(vault, source, [source_entry("e1", likes=0)])
    catalog = sync_with(vault, source, [source_entry("e1", likes=None)])

    history = entry_by_id(catalog, "episodes", "e1")["likes"]
    assert len(history) == 2
    assert current(history) is None
