"""Spec section: Version 2 Catalog/Entry Schema, Version 2 to Version 3 Migration."""

from conftest import ISO_KEY, find_entry, legacy_entry, read_catalog, v2_catalog, write_vault

SOURCE = "https://media.example.com/channel/chan99"


def migrated(run_cli, tmp_path, catalog, name="legacy"):
    """Write a legacy catalog, migrate it, and return the resulting v3 catalog."""
    vault = write_vault(tmp_path, name, catalog)
    result = run_cli("migrate", name)
    assert result.returncode == 0, result.stderr
    return read_catalog(vault)


# Phrase: "`version` | integer | `2`" / "Version detection | Read `version` field"
def test_version_two_catalog_is_readable(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v2_catalog(SOURCE, episodes=[legacy_entry("e1", ISO_KEY)]))
    assert catalog["version"] == 3


# Phrase: "`source` | Preserve existing value"
def test_source_is_preserved(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v2_catalog(SOURCE))
    assert catalog["source"] == SOURCE


# Phrase: "Categories | Preserve `episodes`, `streams`, and `clips` placement"
def test_category_placement_is_preserved(run_cli, tmp_path):
    catalog = migrated(
        run_cli,
        tmp_path,
        v2_catalog(
            SOURCE,
            episodes=[legacy_entry("e1", ISO_KEY)],
            streams=[legacy_entry("s1", ISO_KEY)],
            clips=[legacy_entry("c1", ISO_KEY)],
        ),
    )
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1"]
    assert [entry["id"] for entry in catalog["streams"]] == ["s1"]
    assert [entry["id"] for entry in catalog["clips"]] == ["c1"]


# Phrase: "`removed` | Add `{<migration-timestamp>: false}` to every entry in every category"
def test_removed_is_added_in_every_category(run_cli, tmp_path):
    catalog = migrated(
        run_cli,
        tmp_path,
        v2_catalog(
            SOURCE,
            episodes=[legacy_entry("e1", ISO_KEY)],
            streams=[legacy_entry("s1", ISO_KEY)],
            clips=[legacy_entry("c1", ISO_KEY)],
        ),
    )
    for category in ("episodes", "streams", "clips"):
        assert list(catalog[category][0]["removed"].values()) == [False]


# Phrase: "`annotations` | Add `[]` to every entry"
def test_annotations_are_added_in_every_category(run_cli, tmp_path):
    catalog = migrated(
        run_cli,
        tmp_path,
        v2_catalog(SOURCE, episodes=[legacy_entry("e1", ISO_KEY)], clips=[legacy_entry("c1", ISO_KEY)]),
    )
    assert catalog["episodes"][0]["annotations"] == []
    assert catalog["clips"][0]["annotations"] == []


# Phrase: "`title` | history object | ISO 8601 string keys" - v2 keys are kept as they are
def test_iso_history_keys_are_kept(run_cli, tmp_path):
    entry = legacy_entry("e1", ISO_KEY, views={"2023-01-01T00:00:00": 1, "2024-06-15T09:40:00": 7})
    catalog = migrated(run_cli, tmp_path, v2_catalog(SOURCE, episodes=[entry]))
    assert find_entry(catalog, "episodes", "e1")["views"] == {
        "2023-01-01T00:00:00": 1,
        "2024-06-15T09:40:00": 7,
    }


# Phrase: "Version 2 entries have no `removed` field and no `annotations` field"
def test_v2_entry_without_local_fields_is_accepted(run_cli, tmp_path):
    entry = legacy_entry("e1", ISO_KEY)
    assert "removed" not in entry and "annotations" not in entry
    catalog = migrated(run_cli, tmp_path, v2_catalog(SOURCE, episodes=[entry]))
    assert set(find_entry(catalog, "episodes", "e1")) >= {"removed", "annotations"}


# Phrase: "Version field | Set `version` to `3`" - and no version 1 fields appear
def test_migrated_v2_catalog_has_the_v3_root_shape(run_cli, tmp_path):
    catalog = migrated(run_cli, tmp_path, v2_catalog(SOURCE, episodes=[legacy_entry("e1", ISO_KEY)]))
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Phrase: "Missing categories" is a v1 rule; a v2 catalog missing one is filled in (AMBIGUITIES T16)
def test_v2_catalog_missing_a_category_is_filled_in(run_cli, tmp_path):
    catalog = {"version": 2, "source": SOURCE, "episodes": [legacy_entry("e1", ISO_KEY)]}
    assert migrated(run_cli, tmp_path, catalog)["streams"] == []
