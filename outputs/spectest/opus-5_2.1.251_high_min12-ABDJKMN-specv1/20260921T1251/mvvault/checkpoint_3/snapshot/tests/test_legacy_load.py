"""Spec sections: Supported Versions / Version 1 & 2 schemas / Multi-Version Loading.

Legacy catalogs must be readable by every command without a prior `migrate`.
"""

from __future__ import annotations

import json
from pathlib import Path


def catalog_text(workdir, name="vault"):
    return (Path(workdir) / name / "catalog.json").read_text(encoding="utf-8")


# Spec: | `1` | Supported | Flat `entries` list; `source_id`; UNIX-epoch history keys; ... |
# Context: "Commands that read vault data must handle all supported versions
# without requiring prior migration." A v1 vault is not rejected as invalid.
def test_v1_catalog_is_a_supported_version(run_cli, make_vault, legacy):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    result = run_cli("migrate", "vault")
    assert result.returncode == 0, result.stderr


# Spec: | `2` | Supported | Category arrays; full `source`; ISO 8601 history keys; ... |
def test_v2_catalog_is_a_supported_version(run_cli, make_vault, legacy):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    result = run_cli("migrate", "vault")
    assert result.returncode == 0, result.stderr


# Spec: | `3` | Native format | Category arrays; full `source`; ISO 8601 history
#       keys; `removed`; `annotations` |
def test_v3_is_the_native_format(run_cli, vault, workdir, helpers):
    catalog = helpers.read_catalog(workdir)
    assert catalog["version"] == 3
    assert isinstance(catalog["version"], int)
    for category in ("episodes", "streams", "clips"):
        assert isinstance(catalog[category], list)
    assert isinstance(catalog["source"], str)


# Spec: Version 1 Catalog Schema | `version` | integer | `1` |
#       | `source_id` | string | Short platform identifier |
#       | `entries` | array | All entries in a single flat list |
# Context: a conforming v1 catalog loads; `migrate` proves it was understood.
def test_v1_schema_fields_are_understood(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(source_id="abc", entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert catalog["source"] == legacy.v1_source("abc")
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]


# Spec: Version 1 Entry Schema: `id`, `published`, `width`, `height` and the five
# history objects; "Version 1 entries have no `removed` field and no `annotations`".
def test_v1_entry_static_fields_survive_loading(run_cli, make_vault, legacy, helpers, workdir):
    entry = legacy.v1_entry("e1", published="2024-05-01T08:30:00", width=640, height=480)
    assert "removed" not in entry and "annotations" not in entry
    make_vault(legacy.v1_catalog(entries=[entry]))
    assert run_cli("migrate", "vault").returncode == 0
    stored = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert stored["published"] == "2024-05-01T08:30:00"
    assert stored["width"] == 640
    assert stored["height"] == 480


# Spec: Version 1 Entry Schema | `title`/`description`/`preview` | history object |
#       UNIX-epoch string keys; string values |
#       | `views` | integer values | | `likes` | integer or `null` values |
def test_v1_history_values_survive_loading(run_cli, make_vault, legacy, helpers, workdir):
    epoch = legacy.V1_EPOCH
    entry = legacy.v1_entry(
        "e1", title={epoch: "T"}, description={epoch: "D"}, views={epoch: 7},
        likes={epoch: None}, preview={epoch: "P"})
    make_vault(legacy.v1_catalog(entries=[entry]))
    assert run_cli("migrate", "vault").returncode == 0
    stored = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(stored["title"]) == "T"
    assert helpers.current(stored["description"]) == "D"
    assert helpers.current(stored["views"]) == 7
    assert helpers.current(stored["likes"]) is None
    assert helpers.current(stored["preview"]) == "P"


# Spec: "Version 1 history objects use string representations of UNIX epoch
# seconds as keys (e.g., `\"1718444400\"`). Chronological ordering is determined
# by numeric comparison of these values."
# Context: numeric order, not text order: "9" precedes "1718444400" numerically.
def test_v1_epoch_keys_order_numerically(run_cli, make_vault, legacy, helpers, workdir):
    entry = legacy.v1_entry("e1", title={"9": "older", "1718444400": "newer"})
    make_vault(legacy.v1_catalog(entries=[entry]))
    assert run_cli("migrate", "vault").returncode == 0
    stored = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(stored["title"]) == "newer"


# Spec: Version 2 Catalog Schema: `version` 2, full `source`, `episodes`,
#       `streams`, `clips` arrays.
def test_v2_schema_categories_are_understood(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v2_catalog(
        episodes=[legacy.v2_entry("e1")],
        streams=[legacy.v2_entry("s1")],
        clips=[legacy.v2_entry("c1")],
    ))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Spec: Version 2 Entry Schema: ISO 8601 string keys; "Version 2 entries have no
# `removed` field and no `annotations` field."
def test_v2_entry_iso_keys_are_kept(run_cli, make_vault, legacy, helpers, workdir):
    entry = legacy.v2_entry("e1", title={"2024-01-02T03:04:05": "T"})
    assert "removed" not in entry and "annotations" not in entry
    make_vault(legacy.v2_catalog(episodes=[entry]))
    assert run_cli("migrate", "vault").returncode == 0
    stored = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert stored["title"] == {"2024-01-02T03:04:05": "T"}


# Spec: Version 1 Source Resolution: "The full source URL for a version 1 vault
# is derived deterministically from `source_id`:
# https://media.example.com/channel/<source_id>"
def test_v1_source_is_derived_from_source_id(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(source_id="my-channel"))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert catalog["source"] == "https://media.example.com/channel/my-channel"


# Spec: "All commands that need a source URL for a version 1 vault must use this
# derivation." Context: `sync` fetches the derived URL (unreachable here, so the
# failure names it).
def test_sync_on_v1_uses_derived_source_url(run_cli, make_vault, legacy):
    make_vault(legacy.v1_catalog(source_id="chan-77", entries=[legacy.v1_entry("e1")]))
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "https://media.example.com/channel/chan-77" in result.stderr


# Spec: Multi-Version Loading | Load trigger | Any command that reads a vault
#       (`sync`, `serve`, `digest`, and future commands) |
# Context: `sync` reads the vault; a v2 vault therefore syncs without `migrate`.
def test_sync_reads_a_v2_vault_without_prior_migration(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    result = run_cli("sync", "vault")
    assert result.returncode == 0, result.stderr


# Spec: Multi-Version Loading | Version detection | Read `version` field from
#       `catalog.json` |
# Context: the `version` field, not the shape, selects the reading - a catalog
# declaring `2` while carrying a v1 flat `entries` list is not read as v1.
def test_version_field_selects_the_schema(run_cli, make_vault, legacy, helpers, workdir):
    catalog = legacy.v1_catalog(entries=[legacy.v1_entry("e1")])
    catalog["version"] = 2
    catalog["source"] = "https://example.invalid/feed"
    make_vault(catalog)
    assert run_cli("migrate", "vault").returncode == 0
    migrated = helpers.read_catalog(workdir)
    assert migrated["source"] == "https://example.invalid/feed"
    assert migrated["episodes"] == []


# Spec: Multi-Version Loading | In-memory representation | All versions are
#       usable by every command |
def test_all_versions_usable_by_sync(run_cli, make_vault, legacy, source, helpers, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]), name="v2vault")
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=999)]))
    assert run_cli("sync", "v2vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir, "v2vault"), "e1")
    assert helpers.current(entry["views"]) == 999


# Spec: Multi-Version Loading | Read-only access | Loading a v1 or v2 catalog for
#       a read-only operation does **not** rewrite `catalog.json` |
# Context: a `sync` that fails before its write must leave the legacy catalog on
# disk exactly as it was (the v1 source URL is unreachable here).
def test_read_only_load_of_v1_does_not_rewrite_catalog(run_cli, make_vault, legacy, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    before = catalog_text(workdir)
    assert run_cli("sync", "vault").returncode != 0
    assert catalog_text(workdir) == before
    assert json.loads(catalog_text(workdir))["version"] == 1


# Spec: | Read-only access | ... does not rewrite `catalog.json` |
# Context: a v2 vault whose source cannot be fetched is likewise left untouched.
def test_read_only_load_of_v2_does_not_rewrite_catalog(run_cli, make_vault, legacy, source, workdir):
    catalog = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")])
    catalog["source"] = "http://127.0.0.1:1/unreachable.json"
    make_vault(catalog)
    before = catalog_text(workdir)
    assert run_cli("sync", "vault").returncode != 0
    assert catalog_text(workdir) == before
