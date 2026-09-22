"""Spec: Version 1 to Version 3 Migration."""
import pytest

from conftest import (EPOCH_A, EPOCH_B, ISO_A, ISO_B, TS_RE, V1_SOURCE_PREFIX,
                      find_entry, make_v1_catalog, make_v1_entry, read_catalog)


@pytest.fixture
def migrated(run, tmp_path, make_vault):
    """Migrate a v1 catalog and hand back the v3 catalog written to disk."""

    def _migrate(catalog=None):
        make_vault(make_v1_catalog() if catalog is None else catalog)
        res = run("migrate", "vault")
        assert res.returncode == 0, res
        return read_catalog(tmp_path)

    return _migrate


# Spec: "| `source_id` | Convert to `source` using
# `https://media.example.com/channel/<source_id>` |"
def test_source_id_becomes_derived_source(migrated):
    catalog = migrated(make_v1_catalog(source_id="chan42"))
    assert catalog["source"] == V1_SOURCE_PREFIX + "chan42"


# Spec: "`source_id` | **Convert to** `source` ..." -- the v1-only key does not
# survive into the v3 catalog (see AMBIGUITIES T20).
def test_source_id_key_is_gone(migrated):
    assert "source_id" not in migrated()


# Spec: "| Entries | Move every object from `entries` to `episodes` |"
def test_entries_move_to_episodes(migrated):
    catalog = migrated(make_v1_catalog(entries=[
        make_v1_entry(id="a"), make_v1_entry(id="b"), make_v1_entry(id="c")]))
    assert {e["id"] for e in catalog["episodes"]} == {"a", "b", "c"}


# Spec: "Entries | **Move** every object from `entries` to `episodes`" -- the
# flat list itself is gone (see AMBIGUITIES T20).
def test_entries_key_is_gone(migrated):
    assert "entries" not in migrated()


# Spec: "Entries | Move **every object**..." -- entry content carries over.
def test_moved_entry_keeps_its_static_fields(migrated):
    catalog = migrated(make_v1_catalog(entries=[
        make_v1_entry(id="e1", published="2023-03-04T05:06:07",
                      width=640, height=480)]))
    entry = find_entry(catalog, "episodes", "e1")
    assert entry["published"] == "2023-03-04T05:06:07"
    assert entry["width"] == 640
    assert entry["height"] == 480


# Spec: "| Missing categories | Create empty `streams` and `clips` arrays |"
def test_streams_and_clips_created_empty(migrated):
    catalog = migrated()
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# Spec: "| History keys | Convert every UNIX-epoch string key to ISO 8601
# format |" -- every tracked field, not just the first.
@pytest.mark.parametrize("field", ["title", "description", "views", "likes",
                                   "preview"])
def test_every_history_key_converted(migrated, field):
    catalog = migrated()
    entry = find_entry(catalog, "episodes", "e1")
    assert list(entry[field]) == [ISO_A]
    for key in entry[field]:
        assert TS_RE.match(key), key


# Spec: "History keys | Convert **every** UNIX-epoch string key ..." -- a
# multi-key history converts all of its keys and keeps the values attached.
def test_multi_key_history_converted_with_values(migrated):
    catalog = migrated(make_v1_catalog(entries=[make_v1_entry(
        title={EPOCH_A: "first", EPOCH_B: "second"})]))
    entry = find_entry(catalog, "episodes", "e1")
    assert entry["title"] == {ISO_A: "first", ISO_B: "second"}


# Spec: "History keys | Convert every UNIX-epoch string key to ISO 8601 format"
# -- no epoch-looking key survives anywhere in the catalog.
def test_no_epoch_keys_remain(migrated):
    catalog = migrated(make_v1_catalog(entries=[make_v1_entry(id="a"),
                                                make_v1_entry(id="b")]))
    for entry in catalog["episodes"]:
        for field in ("title", "description", "views", "likes", "preview",
                      "removed"):
            for key in entry[field]:
                assert not key.isdigit(), key


# Spec: "| `removed` | Add `{<migration-timestamp>: false}` to every entry |"
def test_removed_added_to_every_entry(migrated):
    catalog = migrated(make_v1_catalog(entries=[make_v1_entry(id="a"),
                                                make_v1_entry(id="b")]))
    for entry in catalog["episodes"]:
        assert list(entry["removed"].values()) == [False]
        (key,) = list(entry["removed"])
        assert TS_RE.match(key), key


# Spec: "| `annotations` | Add `[]` to every entry |"
def test_annotations_added_to_every_entry(migrated):
    catalog = migrated(make_v1_catalog(entries=[make_v1_entry(id="a"),
                                                make_v1_entry(id="b")]))
    for entry in catalog["episodes"]:
        assert entry["annotations"] == []


# Spec: "| Version field | Set `version` to `3` |"
def test_version_field_set_to_three(migrated):
    assert migrated()["version"] == 3


# Spec: the migrated catalog is the v3 shape: "Category arrays; full `source`;
# ISO 8601 history keys; `removed`; `annotations`".
def test_migrated_v1_catalog_has_the_v3_shape(migrated):
    catalog = migrated()
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}
    entry = catalog["episodes"][0]
    assert set(entry) == {"id", "published", "width", "height", "title",
                          "description", "views", "likes", "preview",
                          "removed", "annotations"}


# Spec: "Entries | Move every object from `entries` to `episodes`" -- an empty
# v1 vault migrates to three empty categories.
def test_empty_v1_catalog_migrates(migrated):
    catalog = migrated(make_v1_catalog(entries=[]))
    assert catalog["episodes"] == []
    assert catalog["streams"] == []
    assert catalog["clips"] == []
    assert catalog["version"] == 3
