"""Spec section: `entry` Stored Fields / `mvault` Determinism (datetime text)."""

import re

from conftest import current, find_entry, read_catalog, source_entry

TRACKED = ("title", "description", "views", "likes", "preview", "removed")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


# Phrase: "Static | `id` / `published` / `width` / `height`"
def test_static_fields_are_stored_as_plain_values(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", published="2024-03-04T05:06:07", width=640, height=480)])
    run_cli("sync", "demo")
    entry = find_entry(read_catalog(vault), "episodes", "e1")
    assert entry["id"] == "e1"
    assert entry["published"] == "2024-03-04T05:06:07"
    assert entry["width"] == 640
    assert entry["height"] == 480


# Phrase: "Tracked | ... | history object"
def test_tracked_fields_are_history_objects(run_cli, source, vault):
    source.serve(streams=[source_entry("s1")])
    run_cli("sync", "demo")
    entry = find_entry(read_catalog(vault), "streams", "s1")
    for field in TRACKED:
        assert isinstance(entry[field], dict), field
        assert entry[field], f"{field} history is empty"


# Phrase: "Tracked | `title` | history object | Values are strings" (and description/preview)
def test_string_tracked_values(run_cli, source, vault):
    source.serve(clips=[source_entry("c1", title="T", description="D", preview="P")])
    run_cli("sync", "demo")
    entry = find_entry(read_catalog(vault), "clips", "c1")
    assert current(entry["title"]) == "T"
    assert current(entry["description"]) == "D"
    assert current(entry["preview"]) == "P"


# Phrase: "Tracked | `views` | history object | Values are integers"
def test_views_values_are_integers(run_cli, source, vault):
    source.serve(clips=[source_entry("c1", views=1234)])
    run_cli("sync", "demo")
    assert current(find_entry(read_catalog(vault), "clips", "c1")["views"]) == 1234


# Phrase: "Tracked | `likes` | history object | Values are integers or `null`"
def test_likes_values_may_be_null(run_cli, source, vault):
    source.serve(clips=[source_entry("c1", likes=None)])
    run_cli("sync", "demo")
    assert current(find_entry(read_catalog(vault), "clips", "c1")["likes"]) is None


# Phrase: "Tracked | `removed` | history object | Values are booleans"
def test_removed_values_are_booleans(run_cli, source, vault):
    source.serve(clips=[source_entry("c1")])
    run_cli("sync", "demo")
    assert current(find_entry(read_catalog(vault), "clips", "c1")["removed"]) is False


# Phrase: "Local-only fields | Source data does not include `removed` or `annotations`"
def test_source_annotations_are_not_stored(run_cli, source, vault):
    source.serve(clips=[source_entry("c1", annotations={"note": "x"}, removed={"2020-01-01T00:00:00": True})])
    run_cli("sync", "demo")
    entry = find_entry(read_catalog(vault), "clips", "c1")
    assert "annotations" not in entry
    assert list(entry["removed"].values()) == [False]


# Phrase: "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix"
def test_history_keys_use_the_required_datetime_text(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    run_cli("sync", "demo")
    entry = find_entry(read_catalog(vault), "episodes", "e1")
    for field in TRACKED:
        for key in entry[field]:
            assert TIMESTAMP.match(key), key


# Phrase: "Date-only source values | Normalize to `00:00:00` time component"
def test_date_only_published_is_normalized(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", published="2024-01-05")])
    run_cli("sync", "demo")
    assert find_entry(read_catalog(vault), "episodes", "e1")["published"] == "2024-01-05T00:00:00"


# Phrase: "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix" (see AMBIGUITIES T2)
def test_published_timezone_suffix_is_dropped(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", published="2024-01-05T06:07:08Z")])
    run_cli("sync", "demo")
    assert find_entry(read_catalog(vault), "episodes", "e1")["published"] == "2024-01-05T06:07:08"


# Phrase: "Static | `published` | string | Original publication datetime" (see AMBIGUITIES T3)
def test_static_fields_keep_their_first_observed_values(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", published="2024-01-05", width=640)])
    run_cli("sync", "demo")
    source.serve(episodes=[source_entry("e1", published="2025-09-09", width=1280)])
    run_cli("sync", "demo")
    entry = find_entry(read_catalog(vault), "episodes", "e1")
    assert entry["published"] == "2024-01-05T00:00:00"
    assert entry["width"] == 640
