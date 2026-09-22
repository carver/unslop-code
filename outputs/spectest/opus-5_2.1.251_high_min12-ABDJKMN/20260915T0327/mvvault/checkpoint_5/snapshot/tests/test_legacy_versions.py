"""Spec sections: `mvault` Supported Versions, Version 1 / Version 2 Catalog
and Entry Schemas, Multi-Version Loading, Version Handling Errors."""
import json
import os

import pytest

from conftest import (
    EPOCH_TO_ISO,
    LEGACY_SOURCE_PREFIX,
    catalog_text,
    entry,
    payload,
    read_catalog,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    write_vault,
)


# --- Phrase: "| `1` | Supported |" (context: Supported Versions table; a v1
#     catalog is accepted by a command that reads a vault)
def test_version_1_catalog_is_supported(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("a")]))
    result = run("migrate", "vault")
    assert result.returncode == 0, result


# --- Phrase: "| `2` | Supported |"
def test_version_2_catalog_is_supported(run, tmp_path):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("a")]))
    result = run("migrate", "vault")
    assert result.returncode == 0, result


# --- Phrase: "| `3` | Native format |"
def test_version_3_catalog_is_supported(run, tmp_path):
    write_vault(tmp_path, v3_catalog())
    result = run("migrate", "vault")
    assert result.returncode == 0, result


# --- Phrase: "Commands that read vault data must handle all supported
#     versions without requiring prior migration."
@pytest.mark.parametrize(
    "catalog",
    [
        v1_catalog(entries=[v1_entry("a")]),
        v2_catalog(episodes=[v2_entry("a")]),
        v3_catalog(),
    ],
    ids=["v1", "v2", "v3"],
)
def test_sync_reads_every_supported_version_without_prior_migration(
    run, source, tmp_path, catalog
):
    if catalog["version"] == 2:
        catalog["source"] = source.url
    if catalog["version"] == 3:
        catalog["source"] = source.url
    write_vault(tmp_path, catalog)
    source.set_payload(payload(episodes=[entry("a")]))
    result = run("sync", "vault")
    if catalog["version"] == 1:
        # The v1 source URL is derived and unreachable here, but the failure
        # must be a source failure -- the catalog itself was understood.
        assert "version" not in result.stderr.lower(), result
    else:
        assert result.returncode == 0, result


# ---------------------------------------------------------------------------
# Version 1 Catalog Schema
# ---------------------------------------------------------------------------

# --- Phrase: "| `source_id` | string | Short platform identifier |" and
#     "| `entries` | array | All entries in a single flat list |"
def test_v1_flat_entries_list_is_loaded(run, tmp_path):
    write_vault(
        tmp_path, v1_catalog(entries=[v1_entry("a"), v1_entry("b")])
    )
    assert run("migrate", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert {e["id"] for e in catalog["episodes"]} == {"a", "b"}


# --- Phrase: "| `title` | history object | UNIX-epoch string keys; string
#     values |" (context: Version 1 Entry Schema; all five tracked fields)
@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "T"),
        ("description", "D"),
        ("views", 7),
        ("likes", 3),
        ("preview", "P"),
    ],
)
def test_v1_history_fields_are_carried_through(run, tmp_path, field, value):
    item = v1_entry("a", **{field: {"1700000000": value}})
    write_vault(tmp_path, v1_catalog(entries=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored[field] == {EPOCH_TO_ISO["1700000000"]: value}


# --- Phrase: "| `likes` | history object | UNIX-epoch string keys; integer or
#     `null` values |"
def test_v1_likes_may_be_null(run, tmp_path):
    item = v1_entry("a", likes={"1700000000": None})
    write_vault(tmp_path, v1_catalog(entries=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored["likes"] == {EPOCH_TO_ISO["1700000000"]: None}


# --- Phrase: "| `id` | string |", "| `published` | string | ISO 8601
#     datetime |", "| `width` | integer |", "| `height` | integer |"
def test_v1_static_fields_are_preserved(run, tmp_path):
    item = v1_entry("a", published="2021-05-04T06:07:08", width=640, height=480)
    write_vault(tmp_path, v1_catalog(entries=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored["id"] == "a"
    assert stored["published"] == "2021-05-04T06:07:08"
    assert stored["width"] == 640
    assert stored["height"] == 480


# --- Phrase: "Version 1 entries have **no** `removed` field and **no**
#     `annotations` field." (context: the loader must not require them)
def test_v1_entry_without_removed_or_annotations_loads(run, tmp_path):
    item = v1_entry("a")
    assert "removed" not in item and "annotations" not in item
    write_vault(tmp_path, v1_catalog(entries=[item]))
    assert run("migrate", "vault").returncode == 0


# ---------------------------------------------------------------------------
# Version 1 UNIX-Epoch History Keys
# ---------------------------------------------------------------------------

# --- Phrase: "Version 1 history objects use string representations of UNIX
#     epoch seconds as keys (e.g., `\"1718444400\"`)."
def test_v1_epoch_key_example_converts(run, tmp_path):
    item = v1_entry("a", stamp="1718444400")
    write_vault(tmp_path, v1_catalog(entries=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert list(stored["title"]) == ["2024-06-15T09:40:00"]


# --- Phrase: "Chronological ordering is determined by numeric comparison of
#     these values." (context: "900" is numerically older than "1700000000"
#     though lexicographically larger)
def test_v1_history_order_uses_numeric_comparison(run, tmp_path):
    item = v1_entry(
        "a", title={"900": "older", "1700000000": "newer"}
    )
    write_vault(tmp_path, v1_catalog(entries=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    iso = sorted(stored["title"])
    assert stored["title"][iso[-1]] == "newer"
    assert stored["title"][iso[0]] == "older"


# ---------------------------------------------------------------------------
# Version 1 Source Resolution
# ---------------------------------------------------------------------------

# --- Phrase: "https://media.example.com/channel/<source_id>"
def test_v1_source_is_derived_from_source_id(run, tmp_path):
    write_vault(tmp_path, v1_catalog(source_id="abc123"))
    assert run("migrate", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert catalog["source"] == LEGACY_SOURCE_PREFIX + "abc123"


# --- Phrase: "All commands that need a source URL for a version 1 vault must
#     use this derivation."
def test_v1_sync_uses_the_derived_source_url(run, tmp_path):
    write_vault(tmp_path, v1_catalog(source_id="zz-9"))
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert LEGACY_SOURCE_PREFIX + "zz-9" in result.stderr, result


# ---------------------------------------------------------------------------
# Version 2 Catalog Schema
# ---------------------------------------------------------------------------

# --- Phrase: "| `source` | string | Full source URL |"
def test_v2_source_is_the_full_url(run, tmp_path):
    write_vault(tmp_path, v2_catalog(source="https://host.test/feed.json"))
    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path)["source"] == "https://host.test/feed.json"


# --- Phrase: "| `episodes` | array |", "| `streams` | array |",
#     "| `clips` | array |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v2_category_arrays_are_loaded(run, tmp_path, category):
    write_vault(tmp_path, v2_catalog(**{category: [v2_entry("a")]}))
    assert run("migrate", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog[category]] == ["a"]


# --- Phrase: "| `title` | history object | ISO 8601 string keys; string
#     values |" (context: Version 2 Entry Schema)
def test_v2_iso_history_keys_are_kept(run, tmp_path):
    item = v2_entry("a", stamp="2022-03-04T05:06:07")
    write_vault(tmp_path, v2_catalog(episodes=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert list(stored["title"]) == ["2022-03-04T05:06:07"]
    assert stored["title"]["2022-03-04T05:06:07"] == "Title a"


# --- Phrase: "| `likes` | history object | ISO 8601 string keys; integer or
#     `null` values |"
def test_v2_likes_may_be_null(run, tmp_path):
    item = v2_entry("a", likes={"2022-03-04T05:06:07": None})
    write_vault(tmp_path, v2_catalog(episodes=[item]))
    assert run("migrate", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored["likes"] == {"2022-03-04T05:06:07": None}


# --- Phrase: "Version 2 entries have **no** `removed` field and **no**
#     `annotations` field."
def test_v2_entry_without_removed_or_annotations_loads(run, tmp_path):
    item = v2_entry("a")
    assert "removed" not in item and "annotations" not in item
    write_vault(tmp_path, v2_catalog(episodes=[item]))
    assert run("migrate", "vault").returncode == 0


# ---------------------------------------------------------------------------
# Multi-Version Loading
# ---------------------------------------------------------------------------

# --- Phrase: "| Load trigger | Any command that reads a vault (`sync`,
#     `serve`, `digest`, and future commands) |"
def test_sync_triggers_legacy_load(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("a")]))
    source.set_payload(payload(episodes=[entry("a")]))
    result = run("sync", "vault")
    assert result.returncode == 0, result
    assert read_catalog(tmp_path)["version"] == 3


# --- Phrase: "| Version detection | Read `version` field from `catalog.json` |"
#     (context: the declared version, not the shape, selects the reader)
def test_version_field_selects_the_reader(run, tmp_path):
    # A v1-shaped catalog that declares version 2 is not a valid v2 catalog.
    catalog = {"version": 2, "source_id": "x", "entries": []}
    write_vault(tmp_path, catalog)
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result


# --- Phrase: "| In-memory representation | All versions are usable by every
#     command |"
def test_v2_vault_is_usable_by_sync_without_migrate_first(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("a")]))
    source.set_payload(payload(episodes=[entry("a", title="fresh")]))
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert "fresh" in stored["title"].values()


# --- Phrase: "| Read-only access | Loading a v1 or v2 catalog for a read-only
#     operation does **not** rewrite `catalog.json` |" (context: a sync that
#     never reaches its write leaves the legacy file byte-identical)
def test_failed_sync_does_not_rewrite_a_legacy_catalog(run, source, tmp_path):
    write_vault(tmp_path, v2_catalog(source=source.url,
                                     episodes=[v2_entry("a")]))
    before = catalog_text(tmp_path)
    source.set_raw("not json", status=200)
    assert run("sync", "vault").returncode != 0
    assert catalog_text(tmp_path) == before


def test_loading_a_legacy_catalog_does_not_write_a_backup(run, source, tmp_path):
    write_vault(tmp_path, v1_catalog(source_id="unreachable"))
    run("sync", "vault")
    assert not os.path.exists(os.path.join(str(tmp_path), "vault", "catalog.bak"))


# ---------------------------------------------------------------------------
# Version Handling Errors
# ---------------------------------------------------------------------------

# --- Phrase: "| Missing `version` field | Error to stderr; exit non-zero; no
#     migration; no modification |"
def test_missing_version_field_errors(run, tmp_path):
    write_vault(tmp_path, {"source": "https://host.test/s.json", "episodes": [],
                           "streams": [], "clips": []})
    before = catalog_text(tmp_path)
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result
    assert catalog_text(tmp_path) == before
    assert not os.path.exists(os.path.join(str(tmp_path), "vault", "catalog.bak"))


def test_missing_version_field_errors_for_sync(run, tmp_path):
    write_vault(tmp_path, {"source": "https://host.test/s.json", "episodes": [],
                           "streams": [], "clips": []})
    before = catalog_text(tmp_path)
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert catalog_text(tmp_path) == before


# --- Phrase: "| Non-integer `version` field | Version-related error to stderr;
#     exit non-zero; no migration; no modification |"
@pytest.mark.parametrize("value", ["3", 3.5, 3.0, None, True, [3], {"n": 3}])
def test_non_integer_version_errors(run, tmp_path, value):
    catalog = v3_catalog()
    catalog["version"] = value
    write_vault(tmp_path, catalog)
    before = catalog_text(tmp_path)
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert "version" in result.stderr.lower(), result
    assert catalog_text(tmp_path) == before


# --- Phrase: "| `version` greater than `3` | Version-related error to stderr;
#     exit non-zero; no migration; no modification |"
@pytest.mark.parametrize("value", [4, 5, 99])
def test_version_greater_than_three_errors(run, tmp_path, value):
    catalog = v3_catalog()
    catalog["version"] = value
    write_vault(tmp_path, catalog)
    before = catalog_text(tmp_path)
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert "version" in result.stderr.lower(), result
    assert catalog_text(tmp_path) == before
    assert not os.path.exists(os.path.join(str(tmp_path), "vault", "catalog.bak"))


def test_version_greater_than_three_errors_for_sync(run, source, tmp_path):
    catalog = v3_catalog(source=source.url)
    catalog["version"] = 4
    write_vault(tmp_path, catalog)
    source.set_payload(payload())
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert "version" in result.stderr.lower(), result


# --- Phrase: "| `version` greater than `3` |" (context: see AMBIGUITIES T16 --
#     versions below 1 are equally unsupported)
@pytest.mark.parametrize("value", [0, -1])
def test_version_below_one_errors(run, tmp_path, value):
    catalog = v3_catalog()
    catalog["version"] = value
    write_vault(tmp_path, catalog)
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert "version" in result.stderr.lower(), result


# --- Phrase: "| Invalid JSON in `catalog.json` | Error to stderr; exit
#     non-zero; no migration |"
def test_invalid_json_catalog_errors(run, tmp_path):
    write_vault(tmp_path, "{not json at all")
    result = run("migrate", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result
    assert catalog_text(tmp_path) == "{not json at all"
    assert not os.path.exists(os.path.join(str(tmp_path), "vault", "catalog.bak"))


def test_invalid_json_catalog_errors_for_sync(run, tmp_path):
    write_vault(tmp_path, "[[[")
    result = run("sync", "vault")
    assert result.returncode != 0, result
    assert result.stderr.strip(), result


# ---------------------------------------------------------------------------
# Version 3 native shape
# ---------------------------------------------------------------------------

# --- Phrase: "| `3` | Native format | Category arrays; full `source`; ISO 8601
#     history keys; `removed`; `annotations` |" (context: entries a native v3
#     command creates carry both local-only fields, see AMBIGUITIES T12)
def test_sync_created_entries_have_removed_and_annotations(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("a")]))
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored["removed"][max(stored["removed"])] is False
    assert stored["annotations"] == []


def test_annotations_survive_a_later_sync(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("a")]))
    assert run("sync", "vault").returncode == 0
    source.set_payload(payload(episodes=[entry("a", title="next")]))
    assert run("sync", "vault").returncode == 0
    stored = read_catalog(tmp_path)["episodes"][0]
    assert stored["annotations"] == []
