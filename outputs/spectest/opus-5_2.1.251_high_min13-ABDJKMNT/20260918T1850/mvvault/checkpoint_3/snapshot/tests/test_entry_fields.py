"""Spec sections: `entry` Stored Fields, `tracked field` History Format."""

import pytest

from conftest import TIMESTAMP_RE, latest, payload, read_catalog, source_entry

STATIC_FIELDS = {"id": "e1", "published": "2024-05-06T07:08:09", "width": 640, "height": 480}
TRACKED_FIELDS = ["title", "description", "views", "likes", "preview", "removed"]


@pytest.fixture
def synced(run, source, vault):
    """A vault holding one episode observed once."""
    source.serve(payload(episodes=[source_entry("e1", **STATIC_FIELDS)]))
    assert run("sync", "vault").returncode == 0
    return read_catalog(vault)["episodes"][0]


# Spec: Static | `id` / `published` / `width` / `height`
def test_static_fields_are_stored_as_plain_values(synced):
    assert synced["id"] == "e1"
    assert synced["published"] == "2024-05-06T07:08:09"
    assert synced["width"] == 640
    assert synced["height"] == 480


# Spec: Tracked | title/description/views/likes/preview/removed | history object
@pytest.mark.parametrize("field", TRACKED_FIELDS)
def test_tracked_fields_are_history_objects(synced, field):
    assert isinstance(synced[field], dict)
    assert synced[field]


# Spec: Static/Tracked field groups (exactly ten stored fields)
def test_entry_has_exactly_the_specified_fields(synced):
    assert set(synced) == {"id", "published", "width", "height", *TRACKED_FIELDS}


# Spec: Tracked | `title` | Values are strings; `description` | Values are strings
def test_text_history_values_are_strings(synced):
    assert isinstance(latest(synced["title"]), str)
    assert isinstance(latest(synced["description"]), str)


# Spec: Tracked | `views` | Values are integers
def test_views_history_values_are_integers(synced):
    value = latest(synced["views"])
    assert isinstance(value, int) and not isinstance(value, bool)


# Spec: Tracked | `likes` | Values are integers or `null`
def test_likes_history_values_are_integers_or_null(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", likes=None)]))
    run("sync", "vault")
    assert latest(read_catalog(vault)["episodes"][0]["likes"]) is None


# Spec: Tracked | `removed` | Values are booleans
def test_removed_history_values_are_booleans(synced):
    assert latest(synced["removed"]) is False


# Spec: Key format | ISO 8601 datetime string
@pytest.mark.parametrize("field", TRACKED_FIELDS)
def test_history_keys_are_iso_datetime_strings(synced, field):
    for key in synced[field]:
        assert TIMESTAMP_RE.match(key), key


# Spec: Value selection | Current value = value at latest datetime key
def test_current_value_is_the_value_at_the_latest_key(run, source, vault):
    for views in (10, 25, 60):
        source.serve(payload(episodes=[source_entry("e1", views=views)]))
        run("sync", "vault")
    history = read_catalog(vault)["episodes"][0]["views"]
    assert len(history) == 3
    assert history[max(history)] == 60


# Spec: Comparison order | Chronological timestamp order
def test_history_reads_chronologically(run, source, vault):
    for title in ("first", "second", "third"):
        source.serve(payload(episodes=[source_entry("e1", title=title)]))
        run("sync", "vault")
    history = read_catalog(vault)["episodes"][0]["title"]
    assert [history[k] for k in sorted(history)] == ["first", "second", "third"]


# Spec: Local-only fields | Source data does not include `removed` or `annotations`
def test_local_only_fields_survive_a_sync(run, source, vault):
    import json

    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")

    catalog = read_catalog(vault)
    catalog["episodes"][0]["annotations"] = {"note": "keep me"}
    (vault / "catalog.json").write_text(json.dumps(catalog))

    source.serve(payload(episodes=[source_entry("e1", views=99)]))
    run("sync", "vault")
    assert read_catalog(vault)["episodes"][0]["annotations"] == {"note": "keep me"}
