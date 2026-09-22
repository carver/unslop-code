"""`entry` Stored Fields and `tracked field` History Format."""

import re

from conftest import current, read_catalog, source_entry

TRACKED = ["title", "description", "views", "likes", "preview", "removed"]
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def synced_entry(run_cli, vault, source, **overrides):
    source.payload = {"episodes": [source_entry("a", **overrides)], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    return read_catalog(vault)["episodes"][0]


# Spec: Static | `id` | string | Source identifier
def test_static_id_is_stored_verbatim(run_cli, vault, source):
    assert synced_entry(run_cli, vault, source)["id"] == "a"


# Spec: Static | `published` | string | Original publication datetime
def test_static_published_is_stored_as_text(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source, published="2022-07-08T05:06:07")
    assert entry["published"] == "2022-07-08T05:06:07"


# Spec: Static | `width` / `height` | integer | Pixel width / height
def test_static_dimensions_are_integers(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source, width=640, height=480)
    assert (entry["width"], entry["height"]) == (640, 480)


# Spec: Static fields are plain values, not history objects
def test_static_fields_are_not_history_objects(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source)
    assert not any(isinstance(entry[field], dict) for field in ("id", "published", "width", "height"))


# Spec: Tracked | `title` / `description` / `views` / `likes` / `preview` / `removed`
# | history object
def test_all_six_tracked_fields_are_history_objects(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source)
    assert all(isinstance(entry[field], dict) for field in TRACKED)


# Spec: Tracked values are strings / integers / booleans as documented
def test_tracked_values_have_documented_types(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source, title="T", description="D", views=5, likes=1, preview="p")
    assert current(entry["title"]) == "T"
    assert current(entry["description"]) == "D"
    assert current(entry["views"]) == 5
    assert current(entry["likes"]) == 1
    assert current(entry["preview"]) == "p"
    assert current(entry["removed"]) is False


# Spec: Tracked | `likes` | history object | Values are integers or `null`
def test_likes_history_accepts_null(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source, likes=None)
    assert current(entry["likes"]) is None


# Spec: Key format | ISO 8601 datetime string
def test_history_keys_are_iso_datetimes(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source)
    assert all(ISO.match(key) for field in TRACKED for key in entry[field])


# Spec: Value selection | Current value = value at latest datetime key
def test_current_value_comes_from_latest_key(run_cli, vault, source):
    synced_entry(run_cli, vault, source, title="first")
    entry = synced_entry(run_cli, vault, source, title="second")
    assert current(entry["title"]) == "second"
    assert len(entry["title"]) == 2


# Spec: Comparison order | Chronological timestamp order
def test_history_keys_are_chronologically_distinguishable(run_cli, vault, source):
    synced_entry(run_cli, vault, source, views=1)
    entry = synced_entry(run_cli, vault, source, views=2)
    keys = list(entry["views"])
    assert sorted(keys) == sorted(keys, key=lambda key: key)
    assert entry["views"][min(keys)] == 1 and entry["views"][max(keys)] == 2


# Spec: Collision handling | When a new history entry would reuse an existing or
# non-newer second, advance to a strictly later second before writing
def test_rapid_syncs_never_reuse_a_second(run_cli, vault, source):
    for views in (1, 2, 3, 4):
        synced_entry(run_cli, vault, source, views=views)
    history = read_catalog(vault)["episodes"][0]["views"]
    assert len(history) == 4
    assert len(set(history)) == 4


# Spec: Collision handling ... advance to a strictly later second before writing
def test_new_history_key_is_strictly_later_than_previous(run_cli, vault, source):
    synced_entry(run_cli, vault, source, title="one")
    first = max(read_catalog(vault)["episodes"][0]["title"])
    synced_entry(run_cli, vault, source, title="two")
    assert max(read_catalog(vault)["episodes"][0]["title"]) > first


# Spec: JSON object key order | Not part of the contract
def test_history_is_read_by_key_not_by_position(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source, title="only")
    assert current(entry["title"]) == entry["title"][max(entry["title"])]


# Spec: Local-only fields | Source data does not include `removed` or `annotations`
def test_entry_has_no_annotations_from_source(run_cli, vault, source):
    entry = synced_entry(run_cli, vault, source)
    assert "annotations" not in entry
