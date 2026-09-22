"""Spec sections: `entry` Stored Fields / `tracked field` History Format / `likes` Null Semantics."""

from __future__ import annotations

import re

TRACKED = ("title", "description", "views", "likes", "preview", "removed")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


# Spec: Static | `id` | string | Source identifier |
def test_static_id_stored_as_string(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["id"] == "e1"
    assert isinstance(entry["id"], str)


# Spec: Static | `published` | string | Original publication datetime |
def test_static_published_stored_as_string(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("e1", published="2023-11-02T06:15:44")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["published"] == "2023-11-02T06:15:44"


# Spec: Static | `width` | integer | Pixel width | ; | `height` | integer | Pixel height |
def test_static_width_height_stored_as_integers(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("e1", width=640, height=360)]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["width"] == 640 and isinstance(entry["width"], int)
    assert entry["height"] == 360 and isinstance(entry["height"], int)


# Spec: Static fields are not history objects (only the six Tracked rows are).
def test_static_fields_are_not_history_objects(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in ("id", "published", "width", "height"):
        assert not isinstance(entry[field], dict)


# Spec: Tracked | `title` / `description` / `views` / `likes` / `preview` / `removed` | history object |
def test_all_six_tracked_fields_are_history_objects(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in TRACKED:
        assert isinstance(entry[field], dict), field
        assert entry[field], f"{field} history is empty"


# Spec: Tracked | `title` | history object | Values are strings |
#       Tracked | `description` | history object | Values are strings |
#       Tracked | `preview` | history object | Values are strings |
def test_tracked_string_field_values(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("e1", title="T", description="D", preview="P")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(entry["title"]) == "T"
    assert helpers.current(entry["description"]) == "D"
    assert helpers.current(entry["preview"]) == "P"
    for field in ("title", "description", "preview"):
        assert all(isinstance(v, str) for v in entry[field].values())


# Spec: Tracked | `views` | history object | Values are integers |
def test_tracked_views_values_are_integers(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=4321)]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(entry["views"]) == 4321
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in entry["views"].values())


# Spec: Tracked | `likes` | history object | Values are integers or `null` |
def test_tracked_likes_values_allow_null(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=None)]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(entry["likes"]) is None


# Spec: Tracked | `removed` | history object | Values are booleans |
def test_tracked_removed_values_are_booleans(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert all(isinstance(v, bool) for v in entry["removed"].values())


# Spec: History Format | Key format | ISO 8601 datetime string |
# Context: Determinism | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |
def test_history_keys_are_iso_datetime_strings(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in TRACKED:
        for key in entry[field]:
            assert ISO_RE.match(key), (field, key)


# Spec: History Format | Value selection | Current value = value at latest datetime key |
def test_current_value_is_value_at_latest_key(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="first")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="second")]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    keys = helpers.keys_sorted(entry["title"])
    assert len(keys) == 2
    assert entry["title"][keys[0]] == "first"
    assert entry["title"][keys[-1]] == "second"


# Spec: History Format | Comparison order | Chronological timestamp order |
# Context: change detection compares against the chronologically latest value,
#          not against insertion order.
def test_change_detection_compares_against_chronologically_latest(
    run_cli, vault, source, helpers, workdir
):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=10)]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=20)]))
    assert run_cli("sync", "vault").returncode == 0
    # views is back to a value seen before, but not the latest one -> a change.
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=10)]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    keys = helpers.keys_sorted(entry["views"])
    assert len(keys) == 3
    assert [entry["views"][k] for k in keys] == [10, 20, 10]


# Spec: History Format | Collision handling | When a new history entry would reuse an
#       existing or non-newer second, advance to a strictly later second before writing |
def test_rapid_syncs_produce_strictly_increasing_keys(run_cli, vault, source, helpers, workdir):
    for views in (1, 2, 3, 4):
        source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=views)]))
        assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    keys = helpers.keys_sorted(entry["views"])
    assert len(keys) == 4, entry["views"]
    assert len(set(keys)) == 4
    assert keys == sorted(keys)
    assert [entry["views"][k] for k in keys] == [1, 2, 3, 4]


# Spec: Collision handling ... "advance to a strictly later second"
# Context: a pre-existing history key in the future forces the next key past it.
def test_new_key_is_strictly_later_than_existing_future_key(
    run_cli, vault, source, helpers, workdir
):
    import json
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=1)]))
    assert run_cli("sync", "vault").returncode == 0

    catalog_path = vault / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = catalog["episodes"][0]
    future = "2999-01-01T00:00:00"
    entry["views"][future] = 1
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=2)]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    keys = helpers.keys_sorted(entry["views"])
    assert keys[-1] > future
    assert entry["views"][keys[-1]] == 2


# Spec: History Format | JSON object key order | Not part of the contract |
# Context: readers must sort keys; the file may store them in any order.
def test_key_order_in_file_is_not_relied_upon(run_cli, vault, source, helpers, workdir):
    import json
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=1)]))
    assert run_cli("sync", "vault").returncode == 0

    catalog_path = vault / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = catalog["episodes"][0]
    history = entry["views"]
    history["1999-01-01T00:00:00"] = 999  # older key appended last in file order
    entry["views"] = history
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    # current value is still the one at the latest key (1), so no change is recorded
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=1)]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(entry["views"]) == 1
    assert len(entry["views"]) == 2


# Spec: History Format | Local-only fields | Source data does not include `removed` or `annotations` |
# Context: a source-provided `removed` must not leak into the entry's history.
def test_source_supplied_removed_does_not_override_local_tracking(
    run_cli, vault, source, helpers, workdir
):
    entry = helpers.make_source_entry("e1")
    entry["removed"] = True
    entry["annotations"] = {"note": "from source"}
    source.set(helpers.make_payload(episodes=[entry]))
    assert run_cli("sync", "vault").returncode == 0

    stored = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(stored["removed"]) is False


# Spec: | Local-only fields | ... `annotations` | -> local annotations survive a sync.
# See AMBIGUITIES.md T8.
def test_local_annotations_are_preserved_across_sync(run_cli, vault, source, helpers, workdir):
    import json
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=1)]))
    assert run_cli("sync", "vault").returncode == 0

    catalog_path = vault / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["episodes"][0]["annotations"] = {"2024-01-01T00:00:00": "mine"}
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=2)]))
    assert run_cli("sync", "vault").returncode == 0

    stored = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert stored["annotations"] == {"2024-01-01T00:00:00": "mine"}


# Spec: `likes` Null Semantics: "A transition between `null` and a numeric value is a change"
def test_likes_null_to_number_is_a_change(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=None)]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=7)]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    keys = helpers.keys_sorted(entry["likes"])
    assert [entry["likes"][k] for k in keys] == [None, 7]


# Spec: `likes` Null Semantics: "A transition between `null` and a numeric value is a change"
def test_likes_number_to_null_is_a_change(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=7)]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=None)]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    keys = helpers.keys_sorted(entry["likes"])
    assert [entry["likes"][k] for k in keys] == [7, None]


# Spec: `likes` Null Semantics: "identical values produce no new history entry"
def test_likes_null_to_null_is_not_a_change(run_cli, vault, source, helpers, workdir):
    for _ in range(2):
        source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=None)]))
        assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert len(entry["likes"]) == 1


# Spec: `likes` Null Semantics: "`null` as an ordinary value" -> 0 and null are different
def test_likes_zero_and_null_are_distinct(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=0)]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", likes=None)]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    keys = helpers.keys_sorted(entry["likes"])
    assert [entry["likes"][k] for k in keys] == [0, None]
