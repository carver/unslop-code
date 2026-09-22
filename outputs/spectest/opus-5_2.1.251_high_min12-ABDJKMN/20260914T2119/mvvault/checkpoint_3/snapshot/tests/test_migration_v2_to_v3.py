"""Spec: Version 2 to Version 3 Migration."""
import pytest

from conftest import (ISO_A, ISO_B, TS_RE, find_entry, make_v2_catalog,
                      make_v2_entry, read_catalog)


@pytest.fixture
def migrated(run, tmp_path, make_vault):
    """Migrate a v2 catalog and hand back the v3 catalog written to disk."""

    def _migrate(catalog=None):
        make_vault(make_v2_catalog() if catalog is None else catalog)
        res = run("migrate", "vault")
        assert res.returncode == 0, res
        return read_catalog(tmp_path)

    return _migrate


# Spec: "| `source` | Preserve existing value |"
def test_source_preserved(migrated):
    catalog = migrated(make_v2_catalog(source="https://example.test/feed.json"))
    assert catalog["source"] == "https://example.test/feed.json"


# Spec: "| Categories | Preserve `episodes`, `streams`, and `clips` placement |"
def test_category_placement_preserved(migrated):
    catalog = migrated(make_v2_catalog(
        episodes=[make_v2_entry(id="e1")],
        streams=[make_v2_entry(id="s1")],
        clips=[make_v2_entry(id="c1")]))
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Spec: "Categories | Preserve ... placement" -- an entry does not move to
# `episodes` the way a v1 entry does.
def test_stream_entry_does_not_become_an_episode(migrated):
    catalog = migrated(make_v2_catalog(episodes=[], streams=[
        make_v2_entry(id="s1")]))
    assert catalog["episodes"] == []
    assert find_entry(catalog, "streams", "s1") is not None


# Spec: "| `removed` | Add `{<migration-timestamp>: false}` to every entry in
# every category |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_removed_added_in_every_category(migrated, category):
    catalog = migrated(make_v2_catalog(
        episodes=[make_v2_entry(id="e1")],
        streams=[make_v2_entry(id="s1")],
        clips=[make_v2_entry(id="c1")]))
    for entry in catalog[category]:
        assert list(entry["removed"].values()) == [False]
        (key,) = list(entry["removed"])
        assert TS_RE.match(key), key


# Spec: "| `annotations` | Add `[]` to every entry |"
def test_annotations_added_to_every_entry(migrated):
    catalog = migrated(make_v2_catalog(
        episodes=[make_v2_entry(id="e1"), make_v2_entry(id="e2")],
        clips=[make_v2_entry(id="c1")]))
    for category in ("episodes", "streams", "clips"):
        for entry in catalog[category]:
            assert entry["annotations"] == []


# Spec: "| Version field | Set `version` to `3` |"
def test_version_field_set_to_three(migrated):
    assert migrated()["version"] == 3


# Spec: v2 already uses "ISO 8601 history keys", so migration leaves the
# existing history untouched (see AMBIGUITIES T19).
def test_existing_history_untouched(migrated):
    catalog = migrated(make_v2_catalog(episodes=[make_v2_entry(
        title={ISO_A: "first", ISO_B: "second"},
        views={ISO_A: 10, ISO_B: 20})]))
    entry = find_entry(catalog, "episodes", "e1")
    assert entry["title"] == {ISO_A: "first", ISO_B: "second"}
    assert entry["views"] == {ISO_A: 10, ISO_B: 20}


# Spec: the migrated catalog is the v3 shape.
def test_migrated_v2_catalog_has_the_v3_shape(migrated):
    catalog = migrated()
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}
    entry = catalog["episodes"][0]
    assert set(entry) == {"id", "published", "width", "height", "title",
                          "description", "views", "likes", "preview",
                          "removed", "annotations"}


# Spec: "Categories | Preserve `episodes`, `streams`, and `clips` placement" --
# empty categories stay empty arrays.
def test_empty_v2_catalog_migrates(migrated):
    catalog = migrated(make_v2_catalog(episodes=[]))
    assert catalog["episodes"] == []
    assert catalog["streams"] == []
    assert catalog["clips"] == []
    assert catalog["version"] == 3
