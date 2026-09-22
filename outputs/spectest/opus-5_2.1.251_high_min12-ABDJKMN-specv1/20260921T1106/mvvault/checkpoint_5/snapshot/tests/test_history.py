"""Spec sections: `entry` Stored Fields / history format / `likes` null
semantics / `sync` Update Rules."""
import re

from conftest import entry, find, latest, payload, read_catalog

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
TRACKED = ("title", "description", "views", "likes", "preview", "removed")


def setup_vault(run, source, entries, name="v"):
    assert run("init", name, source.url).returncode == 0
    source.payload = payload(episodes=entries)
    result = run("sync", name)
    assert result.returncode == 0, result.stderr
    return name


# Phrase: "First observation | Add entry to matching category"
def test_first_observation_adds_entry_to_matching_category(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(streams=[entry("s1")])
    assert run("sync", "v").returncode == 0
    catalog = read_catalog(tmp_path / "v")
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert catalog["episodes"] == [] and catalog["clips"] == []


# Phrase: "Static | `id` / `published` / `width` / `height`"
# Context: static fields are stored as plain values, not histories.
def test_static_fields_stored_as_plain_values(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", published="2024-05-06T07:08:09",
                                    width=1280, height=720)])
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    assert stored["id"] == "e1"
    assert stored["published"] == "2024-05-06T07:08:09"
    assert stored["width"] == 1280 and isinstance(stored["width"], int)
    assert stored["height"] == 720 and isinstance(stored["height"], int)


# Phrase: "First observation | ... create initial history entry for all six
#          tracked fields"
def test_first_observation_creates_six_histories(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", title="A", description="B", views=5,
                                    likes=2, preview="ph")])
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    for field in TRACKED:
        assert isinstance(stored[field], dict), field
        assert len(stored[field]) == 1, field
    assert latest(stored["title"]) == "A"
    assert latest(stored["description"]) == "B"
    assert latest(stored["views"]) == 5
    assert latest(stored["likes"]) == 2
    assert latest(stored["preview"]) == "ph"


# Phrase: "First observation | ... set `removed` to `false` at sync timestamp"
def test_first_observation_sets_removed_false(run, source, tmp_path):
    setup_vault(run, source, [entry("e1")])
    removed = read_catalog(tmp_path / "v")["episodes"][0]["removed"]
    assert list(removed.values()) == [False]
    assert latest(removed) is False


# Phrase: "Key format | ISO 8601 datetime string" +
#         "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix"
def test_history_keys_are_iso_datetimes_without_timezone(run, source, tmp_path):
    setup_vault(run, source, [entry("e1")])
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    for field in TRACKED:
        for key in stored[field]:
            assert TS_RE.match(key), (field, key)


# Phrase: "First observation" — all six tracked fields share the one sync
# timestamp. Context: "create initial history entry ... at sync timestamp".
def test_first_observation_uses_a_single_sync_timestamp(run, source, tmp_path):
    setup_vault(run, source, [entry("e1")])
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    stamps = {list(stored[field])[0] for field in TRACKED}
    assert len(stamps) == 1


# Phrase: "Existing entry, unchanged tracked value | No new history entry for
#          that field"
def test_unchanged_values_add_no_history(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", title="A", views=5)])
    before = read_catalog(tmp_path / "v")["episodes"][0]
    assert run("sync", "v").returncode == 0
    after = read_catalog(tmp_path / "v")["episodes"][0]
    for field in TRACKED:
        assert after[field] == before[field], field


# Phrase: "Existing entry, changed tracked value | Append new history entry at
#          sync timestamp"
def test_changed_value_appends_history(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", title="A")])
    first = read_catalog(tmp_path / "v")["episodes"][0]["title"]
    source.payload = payload(episodes=[entry("e1", title="B")])
    assert run("sync", "v").returncode == 0
    history = read_catalog(tmp_path / "v")["episodes"][0]["title"]
    assert len(history) == 2
    assert set(first) < set(history)          # original entry preserved
    assert latest(history) == "B"


# Phrase: "Value selection | Current value = value at latest datetime key" +
#         "Comparison order | Chronological timestamp order"
def test_current_value_is_value_at_latest_key(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", views=1)])
    for views in (2, 3, 4):
        source.payload = payload(episodes=[entry("e1", views=views)])
        assert run("sync", "v").returncode == 0
    history = read_catalog(tmp_path / "v")["episodes"][0]["views"]
    ordered = [history[k] for k in sorted(history)]
    assert ordered == [1, 2, 3, 4]
    assert latest(history) == 4


# Phrase: "Tracked | `views` | history object | Values are integers"
def test_only_changed_fields_get_new_entries(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", title="A", views=1, preview="p")])
    source.payload = payload(episodes=[entry("e1", title="A", views=9, preview="p")])
    assert run("sync", "v").returncode == 0
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    assert len(stored["views"]) == 2
    assert len(stored["title"]) == 1
    assert len(stored["preview"]) == 1
    assert len(stored["removed"]) == 1


# Phrase: "`likes` change detection treats `null` as an ordinary value.
#          A transition between `null` and a numeric value is a change"
def test_likes_null_to_number_is_a_change(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", likes=None)])
    source.payload = payload(episodes=[entry("e1", likes=7)])
    assert run("sync", "v").returncode == 0
    history = read_catalog(tmp_path / "v")["episodes"][0]["likes"]
    assert len(history) == 2
    assert [history[k] for k in sorted(history)] == [None, 7]


# Phrase: "A transition between `null` and a numeric value is a change"
# Context: the reverse direction, number -> null.
def test_likes_number_to_null_is_a_change(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", likes=7)])
    source.payload = payload(episodes=[entry("e1", likes=None)])
    assert run("sync", "v").returncode == 0
    history = read_catalog(tmp_path / "v")["episodes"][0]["likes"]
    assert len(history) == 2
    assert latest(history) is None


# Phrase: "identical values produce no new history entry"
# Context: null observed twice in a row.
def test_repeated_null_likes_add_no_history(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", likes=None)])
    assert run("sync", "v").returncode == 0
    assert len(read_catalog(tmp_path / "v")["episodes"][0]["likes"]) == 1


# Phrase: "identical values produce no new history entry"
# Context: the same numeric likes value twice.
def test_repeated_numeric_likes_add_no_history(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", likes=0)])
    assert run("sync", "v").returncode == 0
    assert len(read_catalog(tmp_path / "v")["episodes"][0]["likes"]) == 1


# Phrase: "Entry absent from current source | Append `removed: true` at sync
#          timestamp" + "Removal handling | Never delete entry from
#          `catalog.json`"
def test_absent_entry_is_marked_removed_not_deleted(run, source, tmp_path):
    setup_vault(run, source, [entry("e1"), entry("e2")])
    source.payload = payload(episodes=[entry("e1")])
    assert run("sync", "v").returncode == 0
    catalog = read_catalog(tmp_path / "v")
    assert sorted(e["id"] for e in catalog["episodes"]) == ["e1", "e2"]
    gone = find(catalog, "episodes", "e2")
    assert latest(gone["removed"]) is True
    assert len(gone["removed"]) == 2
    assert latest(find(catalog, "episodes", "e1")["removed"]) is False


# Phrase: "Entry absent from current source" — other tracked fields of a
# removed entry keep their last observed history.
def test_removed_entry_keeps_other_histories(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", title="A", views=3)])
    source.payload = payload(episodes=[])
    assert run("sync", "v").returncode == 0
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    assert len(stored["title"]) == 1 and latest(stored["title"]) == "A"
    assert len(stored["views"]) == 1 and latest(stored["views"]) == 3


# Phrase: "Existing entry, unchanged tracked value | No new history entry"
# Context: an entry that stays absent stays `removed: true` without churn.
def test_still_absent_entry_adds_no_further_removed_entries(run, source, tmp_path):
    setup_vault(run, source, [entry("e1")])
    source.payload = payload(episodes=[])
    assert run("sync", "v").returncode == 0
    assert run("sync", "v").returncode == 0
    removed = read_catalog(tmp_path / "v")["episodes"][0]["removed"]
    assert len(removed) == 2
    assert latest(removed) is True


# Phrase: "Previously removed entry reappears | Append `removed: false` at sync
#          timestamp"
def test_reappearing_entry_is_restored(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", title="A")])
    source.payload = payload(episodes=[])
    assert run("sync", "v").returncode == 0
    source.payload = payload(episodes=[entry("e1", title="A")])
    assert run("sync", "v").returncode == 0
    removed = read_catalog(tmp_path / "v")["episodes"][0]["removed"]
    assert [removed[k] for k in sorted(removed)] == [False, True, False]


# Phrase: "Previously removed entry reappears" — a restored entry whose tracked
# values also changed while it was gone records both.
def test_restored_entry_records_changed_values(run, source, tmp_path):
    setup_vault(run, source, [entry("e1", title="A", views=1)])
    source.payload = payload(episodes=[])
    assert run("sync", "v").returncode == 0
    source.payload = payload(episodes=[entry("e1", title="B", views=9)])
    assert run("sync", "v").returncode == 0
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    assert latest(stored["title"]) == "B"
    assert latest(stored["views"]) == 9
    assert latest(stored["removed"]) is False


# Phrase: "Tracked | `removed` | history object | Values are booleans"
def test_removed_values_are_booleans(run, source, tmp_path):
    setup_vault(run, source, [entry("e1")])
    source.payload = payload(episodes=[])
    assert run("sync", "v").returncode == 0
    for value in read_catalog(tmp_path / "v")["episodes"][0]["removed"].values():
        assert isinstance(value, bool)


# Phrase: "First observation | Add entry to matching category"
# Context: categories are tracked independently; the same id in another
# category is a separate entry.
def test_categories_are_independent(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("x1", title="ep")],
                             clips=[entry("x1", title="clip")])
    assert run("sync", "v").returncode == 0
    source.payload = payload(clips=[entry("x1", title="clip")])
    assert run("sync", "v").returncode == 0
    catalog = read_catalog(tmp_path / "v")
    assert latest(find(catalog, "episodes", "x1")["removed"]) is True
    assert latest(find(catalog, "clips", "x1")["removed"]) is False


# Phrase: "Success effect | Update catalog with new, changed, removed, and
#          restored entries"
# Context: one sync covering all four cases at once.
def test_single_sync_handles_new_changed_removed_and_restored(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(episodes=[entry("a", title="A"), entry("b"), entry("c")])
    assert run("sync", "v").returncode == 0
    source.payload = payload(episodes=[entry("a", title="A"), entry("b")])
    assert run("sync", "v").returncode == 0          # c removed
    source.payload = payload(episodes=[entry("a", title="A2"), entry("c"),
                                       entry("d")])
    assert run("sync", "v").returncode == 0

    catalog = read_catalog(tmp_path / "v")
    assert latest(find(catalog, "episodes", "a")["title"]) == "A2"   # changed
    assert latest(find(catalog, "episodes", "b")["removed"]) is True  # removed
    assert latest(find(catalog, "episodes", "c")["removed"]) is False  # restored
    assert len(find(catalog, "episodes", "c")["removed"]) == 3
    assert latest(find(catalog, "episodes", "d")["removed"]) is False  # new
    assert len(find(catalog, "episodes", "d")["removed"]) == 1
