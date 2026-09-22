"""Spec: `entry` Stored Fields, `tracked field` History Format, `likes` Null
Semantics."""
import json

import pytest

from conftest import (TS_RE, TRACKED_FIELDS, current, find_entry, make_entry,
                      read_catalog, sorted_keys)

STATIC_FIELDS = ("id", "published", "width", "height")


@pytest.fixture
def synced(run, source, tmp_path, vault):
    """One episode `e1` synced once."""
    source.serve(episodes=[make_entry(
        id="e1", published="2024-05-01T12:00:00", width=1920, height=1080,
        title="First", description="Desc", views=10, likes=1, preview="p0")])
    assert run("sync", "vault").returncode == 0
    return find_entry(read_catalog(tmp_path), "episodes", "e1")


# Spec: "| Static | `id` | string | Source identifier |"
def test_static_id(synced):
    assert synced["id"] == "e1"
    assert isinstance(synced["id"], str)


# Spec: "| Static | `published` | string | Original publication datetime |"
def test_static_published(synced):
    assert synced["published"] == "2024-05-01T12:00:00"
    assert isinstance(synced["published"], str)


# Spec: "| Static | `width` | integer | Pixel width |"
def test_static_width(synced):
    assert synced["width"] == 1920
    assert isinstance(synced["width"], int)


# Spec: "| Static | `height` | integer | Pixel height |"
def test_static_height(synced):
    assert synced["height"] == 1080
    assert isinstance(synced["height"], int)


# Spec: static fields are stored as plain values, not history objects.
@pytest.mark.parametrize("field", STATIC_FIELDS)
def test_static_fields_are_not_history_objects(synced, field):
    assert not isinstance(synced[field], dict)


# Spec: "| Tracked | `title` | history object | Values are strings |" (and the
# five sibling rows) -- every tracked field is stored as an object.
@pytest.mark.parametrize("field", TRACKED_FIELDS)
def test_tracked_fields_are_history_objects(synced, field):
    assert isinstance(synced[field], dict)
    assert synced[field], "history object must not be empty"


# Spec: "| Tracked | `title` | history object | Values are strings |"
def test_tracked_title_values_are_strings(synced):
    assert all(isinstance(v, str) for v in synced["title"].values())
    assert current(synced["title"]) == "First"


# Spec: "| Tracked | `description` | history object | Values are strings |"
def test_tracked_description_values_are_strings(synced):
    assert all(isinstance(v, str) for v in synced["description"].values())
    assert current(synced["description"]) == "Desc"


# Spec: "| Tracked | `views` | history object | Values are integers |"
def test_tracked_views_values_are_integers(synced):
    assert all(isinstance(v, int) and not isinstance(v, bool)
               for v in synced["views"].values())
    assert current(synced["views"]) == 10


# Spec: "| Tracked | `likes` | history object | Values are integers or `null` |"
def test_tracked_likes_values(synced):
    assert all(v is None or (isinstance(v, int) and not isinstance(v, bool))
               for v in synced["likes"].values())
    assert current(synced["likes"]) == 1


# Spec: "| Tracked | `preview` | history object | Values are strings |"
def test_tracked_preview_values_are_strings(synced):
    assert all(isinstance(v, str) for v in synced["preview"].values())
    assert current(synced["preview"]) == "p0"


# Spec: "| Tracked | `removed` | history object | Values are booleans |"
def test_tracked_removed_values_are_booleans(synced):
    assert all(isinstance(v, bool) for v in synced["removed"].values())
    assert current(synced["removed"]) is False


# Spec: the `entry` Stored Fields table is the full set of stored fields, and
# "Local-only fields | Source data does not include `removed` or `annotations`"
# -- `annotations` is reserved, not created (see AMBIGUITIES T10).
def test_entry_has_exactly_the_documented_fields(synced):
    assert set(synced) == set(STATIC_FIELDS) | set(TRACKED_FIELDS)


# Spec: "| Key format | ISO 8601 datetime string |" together with
# "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix".
@pytest.mark.parametrize("field", TRACKED_FIELDS)
def test_history_keys_are_iso_datetime_strings(synced, field):
    for key in synced[field]:
        assert TS_RE.match(key), key


# Spec: "| Value selection | Current value = value at latest datetime key |"
def test_current_value_is_value_at_latest_key(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="v1")])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", title="v2")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    keys = sorted_keys(entry["title"])
    assert len(keys) == 2
    assert entry["title"][keys[0]] == "v1"
    assert entry["title"][keys[-1]] == "v2"
    assert current(entry["title"]) == "v2"


# Spec: "| Comparison order | Chronological timestamp order |" and
# "History interpretation | Chronological timestamp order" -- a later sync must
# compare against the chronologically latest value, even if the catalog's key
# insertion order says otherwise ("JSON object key order | Not part of the
# contract").
def test_comparison_uses_chronological_order_not_key_order(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="latest")])
    run("sync", "vault")

    path = tmp_path / "vault" / "catalog.json"
    catalog = json.loads(path.read_text())
    entry = catalog["episodes"][0]
    key = sorted_keys(entry["title"])[0]
    # Same value at the newest key, a different value at an older key that is
    # written *after* it in the JSON object.
    entry["title"] = {key: "latest", "2000-01-01T00:00:00": "ancient"}
    path.write_text(json.dumps(catalog))

    source.serve(episodes=[make_entry(id="e1", title="latest")])
    assert run("sync", "vault").returncode == 0

    after = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert len(after["title"]) == 2, "unchanged current value must add no entry"
    assert current(after["title"]) == "latest"


# Spec: "| Collision handling | When a new history entry would reuse an existing
# or non-newer second, advance to a strictly later second before writing |"
def test_collision_advances_to_strictly_later_second(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="a")])
    run("sync", "vault")
    # Back-date nothing: syncs in the same wall-clock second must still produce
    # strictly increasing keys.
    source.serve(episodes=[make_entry(id="e1", title="b")])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", title="c")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    keys = sorted_keys(entry["title"])
    assert len(keys) == 3
    assert keys == sorted(set(keys))
    assert [entry["title"][k] for k in keys] == ["a", "b", "c"]


# Spec: "... would reuse an existing or non-newer second, advance to a strictly
# later second" -- also when the existing key lies in the future.
def test_collision_advances_past_future_key(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", title="a")])
    run("sync", "vault")

    path = tmp_path / "vault" / "catalog.json"
    catalog = json.loads(path.read_text())
    entry = catalog["episodes"][0]
    entry["title"] = {"2999-01-01T00:00:00": "a"}
    path.write_text(json.dumps(catalog))

    source.serve(episodes=[make_entry(id="e1", title="b")])
    assert run("sync", "vault").returncode == 0

    after = find_entry(read_catalog(tmp_path), "episodes", "e1")
    keys = sorted_keys(after["title"])
    assert keys[-1] > "2999-01-01T00:00:00"
    assert after["title"][keys[-1]] == "b"


# Spec: "| JSON object key order | Not part of the contract |" -- the catalog
# must remain readable regardless of the order keys appear in on disk; a
# shuffled-but-equivalent history is still interpreted chronologically.
def test_key_order_on_disk_is_not_contractual(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", views=1)])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", views=2)])
    run("sync", "vault")

    path = tmp_path / "vault" / "catalog.json"
    catalog = json.loads(path.read_text())
    entry = catalog["episodes"][0]
    entry["views"] = dict(reversed(list(entry["views"].items())))
    path.write_text(json.dumps(catalog))

    source.serve(episodes=[make_entry(id="e1", views=2)])
    assert run("sync", "vault").returncode == 0
    after = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert len(after["views"]) == 2
    assert current(after["views"]) == 2


# Spec: "| Local-only fields | Source data does not include `removed` or
# `annotations` |" -- a `removed` key in the source payload is not a tracked
# source field; the entry's own `removed` history stays locally managed.
def test_source_removed_field_is_local_only(run, source, tmp_path, vault):
    entry = make_entry(id="e1")
    entry["removed"] = True
    entry["annotations"] = {"note": "hi"}
    source.serve(episodes=[entry])
    assert run("sync", "vault").returncode == 0

    stored = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert current(stored["removed"]) is False
    assert isinstance(stored["removed"], dict)


# Spec: "Local-only fields ... `annotations`" -- a locally added `annotations`
# value survives syncing (see AMBIGUITIES T10).
def test_local_annotations_preserved_across_sync(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", views=1)])
    run("sync", "vault")

    path = tmp_path / "vault" / "catalog.json"
    catalog = json.loads(path.read_text())
    catalog["episodes"][0]["annotations"] = {"2024-01-01T00:00:00": "mine"}
    path.write_text(json.dumps(catalog))

    source.serve(episodes=[make_entry(id="e1", views=2)])
    assert run("sync", "vault").returncode == 0
    stored = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert stored["annotations"] == {"2024-01-01T00:00:00": "mine"}


# ---------------------------------------------------------------------------
# `likes` Null Semantics
# ---------------------------------------------------------------------------

# Spec: "`likes` change detection treats `null` as an ordinary value. A
# transition between `null` and a numeric value is a change" -- numeric -> null.
def test_likes_number_to_null_is_a_change(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", likes=5)])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", likes=None)])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    keys = sorted_keys(entry["likes"])
    assert len(keys) == 2
    assert entry["likes"][keys[0]] == 5
    assert entry["likes"][keys[1]] is None


# Spec: "A transition between `null` and a numeric value is a change" --
# null -> numeric.
def test_likes_null_to_number_is_a_change(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", likes=None)])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", likes=7)])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert len(entry["likes"]) == 2
    assert current(entry["likes"]) == 7


# Spec: "identical values produce no new history entry" -- null stays null.
def test_likes_null_to_null_is_not_a_change(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", likes=None)])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", likes=None)])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert len(entry["likes"]) == 1
    assert current(entry["likes"]) is None


# Spec: "identical values produce no new history entry" -- number stays number.
def test_likes_same_number_is_not_a_change(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", likes=3)])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", likes=3)])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert len(entry["likes"]) == 1


# Spec: "`likes` change detection treats `null` as an ordinary value" -- a
# `likes` of 0 is not conflated with `null`.
def test_likes_zero_and_null_are_distinct(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", likes=0)])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", likes=None)])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    keys = sorted_keys(entry["likes"])
    assert len(keys) == 2
    assert entry["likes"][keys[0]] == 0
    assert entry["likes"][keys[1]] is None
