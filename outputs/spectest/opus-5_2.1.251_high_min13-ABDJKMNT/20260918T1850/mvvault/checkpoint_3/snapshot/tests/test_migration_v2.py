"""Spec sections: Version 2 Catalog/Entry Schema, Version 2 to Version 3 Migration."""

from conftest import V2_STAMP, all_entries, migrated, v2_catalog, v2_entry


# Spec: `source` | Preserve existing value
def test_source_url_is_preserved(run, tmp_path):
    catalog = migrated(run, tmp_path, v2_catalog(source="http://host.invalid/feed.json"))
    assert catalog["source"] == "http://host.invalid/feed.json"


# Spec: Categories | Preserve `episodes`, `streams`, and `clips` placement
def test_category_placement_is_preserved(run, tmp_path):
    catalog = migrated(
        run,
        tmp_path,
        v2_catalog(episodes=[v2_entry("e1")], streams=[v2_entry("s1")], clips=[v2_entry("c1")]),
    )

    assert [entry["id"] for entry in catalog["episodes"]] == ["e1"]
    assert [entry["id"] for entry in catalog["streams"]] == ["s1"]
    assert [entry["id"] for entry in catalog["clips"]] == ["c1"]


# Spec: `removed` | Add `{<migration-timestamp>: false}` to every entry in every category
def test_removed_history_is_added_in_every_category(run, tmp_path):
    catalog = migrated(
        run,
        tmp_path,
        v2_catalog(episodes=[v2_entry("e1")], streams=[v2_entry("s1")], clips=[v2_entry("c1")]),
    )

    for entry in all_entries(catalog):
        assert list(entry["removed"].values()) == [False], entry["id"]


# Spec: `annotations` | Add `[]` to every entry
def test_annotations_are_added_in_every_category(run, tmp_path):
    catalog = migrated(
        run,
        tmp_path,
        v2_catalog(episodes=[v2_entry("e1")], streams=[v2_entry("s1")], clips=[v2_entry("c1")]),
    )

    for entry in all_entries(catalog):
        assert entry["annotations"] == [], entry["id"]


# Spec: Version field | Set `version` to `3`
def test_version_field_becomes_three(run, tmp_path):
    assert migrated(run, tmp_path, v2_catalog(episodes=[v2_entry("e1")]))["version"] == 3


# Spec: Version 2 Entry Schema | `title`/`description`/`views`/`likes`/`preview` |
# ISO 8601 string keys (kept as they are, unlike v1 epoch keys)
def test_iso_history_keys_are_kept_verbatim(run, tmp_path):
    entry = v2_entry("e1", title={V2_STAMP: "first", "2024-07-01T00:00:00": "second"})
    catalog = migrated(run, tmp_path, v2_catalog(episodes=[entry]))

    assert catalog["episodes"][0]["title"] == {
        V2_STAMP: "first",
        "2024-07-01T00:00:00": "second",
    }


# Spec: Version 2 Entry Schema | `id`, `published`, `width`, `height`
def test_static_entry_fields_survive_migration(run, tmp_path):
    entry = v2_entry("e1", published="2022-02-02T02:02:02", width=320, height=240)
    catalog = migrated(run, tmp_path, v2_catalog(episodes=[entry]))

    stored = catalog["episodes"][0]
    assert (stored["published"], stored["width"], stored["height"]) == (
        "2022-02-02T02:02:02",
        320,
        240,
    )


# Spec: Version 2 Entry Schema | `likes` | ... integer or `null` values
def test_null_likes_survive_migration(run, tmp_path):
    entry = v2_entry("e1", likes={V2_STAMP: None})
    catalog = migrated(run, tmp_path, v2_catalog(episodes=[entry]))

    assert catalog["episodes"][0]["likes"] == {V2_STAMP: None}


# Spec: Version 2 Catalog Schema | `episodes`/`streams`/`clips` arrays (empty ones stay empty)
def test_empty_categories_stay_empty(run, tmp_path):
    catalog = migrated(run, tmp_path, v2_catalog(episodes=[v2_entry("e1")]))
    assert catalog["streams"] == [] and catalog["clips"] == []
