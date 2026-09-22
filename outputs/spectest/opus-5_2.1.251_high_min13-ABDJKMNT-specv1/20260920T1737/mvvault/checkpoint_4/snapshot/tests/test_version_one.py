"""Spec section: Version 1 Catalog/Entry Schema, UNIX-Epoch Keys, Source Resolution,
Version 1 to Version 3 Migration."""

from conftest import (
    EPOCH_KEY,
    EPOCH_KEY_AS_ISO,
    current,
    find_entry,
    history_order,
    legacy_entry,
    read_catalog,
    v1_catalog,
    write_vault,
)

TRACKED = ("title", "description", "views", "likes", "preview")


def migrated(run_cli, tmp_path, catalog, name="legacy"):
    """Write a legacy catalog, migrate it, and return the resulting v3 catalog."""
    vault = write_vault(tmp_path, name, catalog)
    result = run_cli("migrate", name)
    assert result.returncode == 0, result.stderr
    return read_catalog(vault)


# Phrase: "`version` | integer | `1`" / "Version detection | Read `version` field from `catalog.json`"
def test_version_one_catalog_is_readable(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    assert catalog["version"] == 3


# Phrase: "`source_id` | Convert to `source` using `https://media.example.com/channel/<source_id>`"
def test_source_id_becomes_the_derived_source_url(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v1_catalog(legacy_entry("e1", EPOCH_KEY), source_id="chan42"))
    assert catalog["source"] == "https://media.example.com/channel/chan42"
    assert "source_id" not in catalog


# Phrase: "Entries | Move every object from `entries` to `episodes`"
def test_every_entry_moves_to_episodes(run_cli, tmp_path):
    entries = [legacy_entry("e1", EPOCH_KEY), legacy_entry("e2", EPOCH_KEY), legacy_entry("e3", EPOCH_KEY)]
    catalog = migrated(run_cli, tmp_path, v1_catalog(*entries))
    assert {entry["id"] for entry in catalog["episodes"]} == {"e1", "e2", "e3"}


# Phrase: "Missing categories | Create empty `streams` and `clips` arrays"
def test_missing_categories_become_empty_arrays(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# Phrase: "History keys | Convert every UNIX-epoch string key to ISO 8601 format"
def test_epoch_keys_become_iso_keys_in_every_tracked_field(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    entry = find_entry(catalog, "episodes", "e1")
    for field in TRACKED:
        assert list(entry[field]) == [EPOCH_KEY_AS_ISO]


# Phrase: "Convert each epoch-seconds key to `YYYY-MM-DDTHH:MM:SS` in UTC"
def test_epoch_conversion_uses_utc(run_cli, tmp_path):
    entry = legacy_entry("e1", EPOCH_KEY, title={"1600000000": "old", "1704067200": "new"})
    catalog = migrated(run_cli, tmp_path, v1_catalog(entry))
    title = find_entry(catalog, "episodes", "e1")["title"]
    assert title == {"2020-09-13T12:26:40": "old", "2024-01-01T00:00:00": "new"}


# Phrase: "Chronological ordering is determined by numeric comparison of these values"
def test_epoch_keys_order_numerically_not_lexicographically(run_cli, tmp_path):
    # "999999999" (2001) sorts after "1700000000" as text, but before it in time.
    entry = legacy_entry("e1", EPOCH_KEY, views={"999999999": 1, "1700000000": 2})
    catalog = migrated(run_cli, tmp_path, v1_catalog(entry))
    views = find_entry(catalog, "episodes", "e1")["views"]
    assert history_order(views) == ["2001-09-09T01:46:39", "2023-11-14T22:13:20"]
    assert current(views) == 2


# Phrase: "`removed` | Add `{<migration-timestamp>: false}` to every entry"
def test_removed_history_is_added_with_a_single_false_value(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v1_catalog(legacy_entry("e1", EPOCH_KEY), legacy_entry("e2", EPOCH_KEY)))
    for entry in catalog["episodes"]:
        assert list(entry["removed"].values()) == [False]


# Phrase: "Each migration-added `removed` timestamp must be ISO 8601"
def test_removed_timestamp_is_iso_8601(run_cli, tmp_path):
    from datetime import datetime

    catalog = migrated(run_cli, tmp_path, v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    key = next(iter(find_entry(catalog, "episodes", "e1")["removed"]))
    assert datetime.fromisoformat(key)


# Phrase: "`annotations` | Add `[]` to every entry"
def test_annotations_are_added_as_empty_lists(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v1_catalog(legacy_entry("e1", EPOCH_KEY), legacy_entry("e2", EPOCH_KEY)))
    for entry in catalog["episodes"]:
        assert entry["annotations"] == []


# Phrase: "`id` ... `published` ... `width` ... `height`" - static fields survive unchanged
def test_static_fields_are_carried_over(run_cli, tmp_path):
    entry = legacy_entry("e1", EPOCH_KEY, published="2021-07-04T12:00:00", width=640, height=360)
    catalog = migrated(run_cli, tmp_path, v1_catalog(entry))
    migrated_entry = find_entry(catalog, "episodes", "e1")
    assert (migrated_entry["published"], migrated_entry["width"], migrated_entry["height"]) == (
        "2021-07-04T12:00:00",
        640,
        360,
    )


# Phrase: "`likes` | history object | ... integer or `null` values"
def test_null_likes_survive_migration(run_cli, tmp_path):
    entry = legacy_entry("e1", EPOCH_KEY, likes={EPOCH_KEY: None})
    catalog = migrated(run_cli, tmp_path, v1_catalog(entry))
    assert find_entry(catalog, "episodes", "e1")["likes"] == {EPOCH_KEY_AS_ISO: None}


# Phrase: "Version 1 entries have no `removed` field and no `annotations` field"
def test_v1_entries_need_no_local_only_fields(run_cli, tmp_path):
    entry = legacy_entry("e1", EPOCH_KEY)
    assert "removed" not in entry and "annotations" not in entry
    catalog = migrated(run_cli, tmp_path, v1_catalog(entry))
    assert set(find_entry(catalog, "episodes", "e1")) >= {"removed", "annotations"}


# Phrase: "All commands that need a source URL for a version 1 vault must use this derivation"
def test_sync_of_a_v1_vault_requests_the_derived_url(run_cli, tmp_path):
    write_vault(tmp_path, "legacy", v1_catalog(legacy_entry("e1", EPOCH_KEY), source_id="chan42"))
    result = run_cli("sync", "legacy")
    assert result.returncode != 0
    assert "https://media.example.com/channel/chan42" in result.stderr
