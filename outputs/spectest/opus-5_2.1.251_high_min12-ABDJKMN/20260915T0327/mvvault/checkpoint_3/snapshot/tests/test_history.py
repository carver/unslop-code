"""Spec sections: `tracked field` History Format, `likes` Null Semantics,
`sync` Update Rules."""
import re

import pytest

from conftest import current, entry, find, history_keys, payload, read_catalog

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
TRACKED = ["title", "description", "views", "likes", "preview", "removed"]


# --- Phrase: "Key format | ISO 8601 datetime string"
def test_history_keys_are_iso_datetime_strings(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    for field in TRACKED:
        for key in stored[field]:
            assert ISO.match(key), (field, key)


# --- Phrase: "Value selection | Current value = value at latest datetime key"
#     + "Existing entry, changed tracked value | Append new history entry at
#     sync timestamp"
def test_changed_value_appends_and_becomes_current(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", title="First")]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", title="Second")]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    keys = history_keys(stored, "title")
    assert len(keys) == 2, stored["title"]
    assert stored["title"][keys[0]] == "First"
    assert stored["title"][keys[1]] == "Second"
    assert current(stored, "title") == "Second"


# --- Phrase: "Existing entry, unchanged tracked value | No new history entry
#     for that field"
def test_unchanged_values_do_not_append(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    run("sync", "vault")
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    for field in TRACKED:
        assert len(stored[field]) == 1, (field, stored[field])


# --- Phrase: "Existing entry, changed tracked value | Append new history entry"
#     (context: only the field that changed gains an entry)
def test_only_changed_field_appends(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", views=1)]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", views=2)]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert len(stored["views"]) == 2
    for field in ["title", "description", "likes", "preview", "removed"]:
        assert len(stored[field]) == 1, field


# --- Phrase: "Tracked | `views` | history object | Values are integers" and
#     "Tracked | `title`/`description`/`preview` ... Values are strings"
def test_history_value_types(run, source, vault, tmp_path):
    source.set_payload(
        payload(episodes=[entry("e1", views=123, likes=45, title="T", preview="p")])
    )
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert isinstance(current(stored, "views"), int)
    assert isinstance(current(stored, "likes"), int)
    assert isinstance(current(stored, "title"), str)
    assert isinstance(current(stored, "description"), str)
    assert isinstance(current(stored, "preview"), str)
    assert isinstance(current(stored, "removed"), bool)


# --- Phrase: "Static fields" (context: static fields never become histories
#     and are not re-versioned when the source changes them)
def test_static_fields_are_not_histories(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", width=100, height=50)]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", width=999, height=999)]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert not isinstance(stored["width"], dict)
    assert not isinstance(stored["published"], dict)


# --- Phrase: "`likes` change detection treats `null` as an ordinary value. A
#     transition between `null` and a numeric value is a change"
def test_likes_number_to_null_is_a_change(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", likes=5)]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", likes=None)]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert len(stored["likes"]) == 2, stored["likes"]
    assert current(stored, "likes") is None


def test_likes_null_to_number_is_a_change(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", likes=None)]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", likes=8)]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert len(stored["likes"]) == 2, stored["likes"]
    assert current(stored, "likes") == 8


# --- Phrase: "identical values produce no new history entry" (context: null)
def test_repeated_null_likes_produce_no_entry(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", likes=None)]))
    run("sync", "vault")
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert len(stored["likes"]) == 1, stored["likes"]


# --- Phrase: "`likes` change detection treats `null` as an ordinary value"
#     (context: 0 and null are distinct values, not both "falsey empty")
def test_zero_likes_and_null_likes_are_distinct(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", likes=0)]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", likes=None)]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert len(stored["likes"]) == 2, stored["likes"]
    assert current(stored, "likes") is None


# --- Phrase: "Entry absent from current source | Append `removed: true` at
#     sync timestamp" + "Removal handling | Never delete entry from
#     `catalog.json`"
def test_absent_entry_is_marked_removed_but_kept(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1"), entry("e2")]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert sorted(e["id"] for e in catalog["episodes"]) == ["e1", "e2"]
    gone = find(catalog, "e2")
    assert current(gone, "removed") is True
    assert len(gone["removed"]) == 2
    assert current(find(catalog, "e1"), "removed") is False


# --- Phrase: "Entry absent from current source" (context: an already-removed
#     entry is unchanged, so no second `removed: true` is appended)
def test_repeated_absence_appends_only_once(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    source.set_payload(payload())
    run("sync", "vault")
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert len(stored["removed"]) == 2, stored["removed"]
    assert current(stored, "removed") is True


# --- Phrase: "Entry absent from current source" (context: tracked values other
#     than `removed` are frozen while the entry is absent)
def test_absence_does_not_touch_other_tracked_fields(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", title="Keep", views=4)]))
    run("sync", "vault")
    source.set_payload(payload())
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert len(stored["title"]) == 1
    assert len(stored["views"]) == 1
    assert current(stored, "title") == "Keep"


# --- Phrase: "Previously removed entry reappears | Append `removed: false` at
#     sync timestamp"
def test_reappearance_appends_removed_false(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    source.set_payload(payload())
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    keys = history_keys(stored, "removed")
    assert [stored["removed"][k] for k in keys] == [False, True, False]


# --- Phrase: "Previously removed entry reappears" (context: values that
#     changed while the entry was away are recorded on return)
def test_reappearance_records_changed_values(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", views=1)]))
    run("sync", "vault")
    source.set_payload(payload())
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", views=9)]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert current(stored, "views") == 9
    assert len(stored["views"]) == 2


# --- Phrase: "Collision handling | When a new history entry would reuse an
#     existing or non-newer second, advance to a strictly later second before
#     writing"
def test_rapid_changes_get_strictly_increasing_keys(run, source, vault, tmp_path):
    for i in range(4):
        source.set_payload(payload(episodes=[entry("e1", title="T%d" % i)]))
        assert run("sync", "vault").returncode == 0
    stored = find(read_catalog(tmp_path), "e1")
    keys = history_keys(stored, "title")
    assert len(keys) == 4, stored["title"]
    assert keys == sorted(set(keys))
    assert [stored["title"][k] for k in keys] == ["T0", "T1", "T2", "T3"]


# --- Phrase: "Comparison order | Chronological timestamp order" +
#     "Sync timestamps ... remain strictly increasing whenever new history
#     entries are appended" (context: across fields and entries)
def test_timestamps_increase_across_syncs(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1"), entry("e2")]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", views=2)]))
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    e1 = find(catalog, "e1")
    e2 = find(catalog, "e2")
    first = history_keys(e1, "title")[0]
    assert history_keys(e1, "views")[1] > first
    assert history_keys(e2, "removed")[1] > first


# --- Phrase: "Collision handling ..." (context: a clock that has not advanced
#     must still yield a usable key for a brand-new entry)
def test_new_entry_in_colliding_sync_gets_later_key(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", title="a")]))
    run("sync", "vault")
    source.set_payload(
        payload(episodes=[entry("e1", title="b"), entry("e2", title="c")])
    )
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    e1 = find(catalog, "e1")
    e2 = find(catalog, "e2")
    first = history_keys(e1, "title")[0]
    assert history_keys(e1, "title")[1] > first
    assert history_keys(e2, "title")[0] > first


# --- Phrase: "JSON object key order | Not part of the contract" (context:
#     history must be interpreted by chronological key order, not file order)
def test_history_is_read_by_chronological_order_not_file_order(
    run, source, vault, tmp_path
):
    import json

    source.set_payload(payload(episodes=[entry("e1", title="old")]))
    run("sync", "vault")
    path = tmp_path / "vault" / "catalog.json"
    catalog = json.loads(path.read_text())
    stored = catalog["episodes"][0]
    (existing,) = list(stored["title"])
    # Rewrite with keys deliberately out of order: newest first in the file.
    stored["title"] = {"2030-01-01T00:00:00": "newest", existing: "old"}
    path.write_text(json.dumps(catalog))
    source.set_payload(payload(episodes=[entry("e1", title="newest")]))
    assert run("sync", "vault").returncode == 0
    stored = find(read_catalog(tmp_path), "e1")
    assert len(stored["title"]) == 2, stored["title"]


# --- Phrase: "Collision handling ... advance to a strictly later second"
#     (context: a future-dated existing key forces the new key past it)
def test_future_key_forces_later_write(run, source, vault, tmp_path):
    import json

    source.set_payload(payload(episodes=[entry("e1", views=1)]))
    run("sync", "vault")
    path = tmp_path / "vault" / "catalog.json"
    catalog = json.loads(path.read_text())
    catalog["episodes"][0]["views"] = {"2090-01-01T00:00:00": 1}
    path.write_text(json.dumps(catalog))
    source.set_payload(payload(episodes=[entry("e1", views=2)]))
    assert run("sync", "vault").returncode == 0
    stored = find(read_catalog(tmp_path), "e1")
    keys = history_keys(stored, "views")
    assert keys[-1] > "2090-01-01T00:00:00", keys
    assert current(stored, "views") == 2
