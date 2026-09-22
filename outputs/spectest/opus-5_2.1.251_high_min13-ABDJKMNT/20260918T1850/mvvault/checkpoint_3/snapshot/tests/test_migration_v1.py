"""Spec sections: Version 1 Catalog/Entry Schema, Source Resolution, v1->v3 Migration."""

from conftest import (
    TIMESTAMP_RE,
    V1_EPOCH,
    V1_EPOCH_ISO,
    V1_SOURCE_TEMPLATE,
    latest,
    migrated,
    v1_catalog,
    v1_entry,
)


# Spec: `source_id` | Convert to `source` using `https://media.example.com/channel/<source_id>`
def test_source_id_becomes_the_derived_source_url(run, tmp_path):
    catalog = migrated(run, tmp_path, v1_catalog(source_id="abc123"))
    assert catalog["source"] == "https://media.example.com/channel/abc123"
    assert "source_id" not in catalog


# Spec: The full source URL for a version 1 vault is derived deterministically from `source_id`
def test_source_derivation_uses_the_exact_template(run, tmp_path):
    catalog = migrated(run, tmp_path, v1_catalog(source_id="chan-9"))
    assert catalog["source"] == V1_SOURCE_TEMPLATE.format("chan-9")


# Spec: Entries | Move every object from `entries` to `episodes`
def test_every_entry_moves_to_episodes(run, tmp_path):
    entries = [v1_entry("e1"), v1_entry("e2"), v1_entry("e3")]
    catalog = migrated(run, tmp_path, v1_catalog(entries=entries))

    assert sorted(entry["id"] for entry in catalog["episodes"]) == ["e1", "e2", "e3"]
    assert "entries" not in catalog


# Spec: Missing categories | Create empty `streams` and `clips` arrays
def test_missing_categories_become_empty_arrays(run, tmp_path):
    catalog = migrated(run, tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# Spec: History keys | Convert every UNIX-epoch string key to ISO 8601 format
def test_every_history_key_is_converted_to_iso_8601(run, tmp_path):
    catalog = migrated(run, tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    entry = catalog["episodes"][0]

    for field in ("title", "description", "views", "likes", "preview"):
        assert list(entry[field]) == [V1_EPOCH_ISO], field


# Spec: v1 UNIX-epoch conversion | Convert each epoch-seconds key to `YYYY-MM-DDTHH:MM:SS` in UTC
def test_epoch_keys_convert_in_utc(run, tmp_path):
    entry = v1_entry("e1", title={"0": "epoch", "1700000000": "later"})
    catalog = migrated(run, tmp_path, v1_catalog(entries=[entry]))

    assert set(catalog["episodes"][0]["title"]) == {
        "1970-01-01T00:00:00",
        "2023-11-14T22:13:20",
    }


# Spec: Chronological ordering is determined by numeric comparison of these values
def test_history_order_follows_numeric_epoch_comparison(run, tmp_path):
    entry = v1_entry("e1", title={"999999999": "older", "1718444400": "newer"})
    catalog = migrated(run, tmp_path, v1_catalog(entries=[entry]))

    assert latest(catalog["episodes"][0]["title"]) == "newer"


# Spec: `removed` | Add `{<migration-timestamp>: false}` to every entry
def test_removed_history_is_added_to_every_entry(run, tmp_path):
    entries = [v1_entry("e1"), v1_entry("e2")]
    catalog = migrated(run, tmp_path, v1_catalog(entries=entries))

    for entry in catalog["episodes"]:
        assert list(entry["removed"].values()) == [False]


# Spec: `annotations` | Add `[]` to every entry
def test_annotations_are_added_to_every_entry(run, tmp_path):
    entries = [v1_entry("e1"), v1_entry("e2")]
    catalog = migrated(run, tmp_path, v1_catalog(entries=entries))

    for entry in catalog["episodes"]:
        assert entry["annotations"] == []


# Spec: Version field | Set `version` to `3`
def test_version_field_becomes_three(run, tmp_path):
    assert migrated(run, tmp_path, v1_catalog(entries=[v1_entry("e1")]))["version"] == 3


# Spec: Version 1 Entry Schema | `id`, `published`, `width`, `height` (carried over unchanged)
def test_static_entry_fields_survive_migration(run, tmp_path):
    entry = v1_entry("e1", published="2023-05-06T07:08:09", width=640, height=480)
    catalog = migrated(run, tmp_path, v1_catalog(entries=[entry]))

    stored = catalog["episodes"][0]
    assert (stored["id"], stored["published"]) == ("e1", "2023-05-06T07:08:09")
    assert (stored["width"], stored["height"]) == (640, 480)


# Spec: Version 1 Entry Schema | `likes` | ... integer or `null` values
def test_history_values_survive_migration(run, tmp_path):
    entry = v1_entry("e1", likes={V1_EPOCH: None, "1718448000": 7}, views={V1_EPOCH: 500})
    catalog = migrated(run, tmp_path, v1_catalog(entries=[entry]))

    stored = catalog["episodes"][0]
    assert stored["likes"] == {V1_EPOCH_ISO: None, "2024-06-15T10:40:00": 7}
    assert stored["views"] == {V1_EPOCH_ISO: 500}


# Spec: Migration-added timestamp scope | Each migration-added `removed` timestamp must be ISO 8601
def test_migration_timestamp_is_iso_8601(run, tmp_path):
    catalog = migrated(run, tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    stamp, = catalog["episodes"][0]["removed"]
    assert TIMESTAMP_RE.match(stamp)
