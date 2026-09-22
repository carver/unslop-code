"""Spec sections: `migrate` Command / v1-to-v3 / v2-to-v3 / Migration Persistence."""

import re

import pytest

from conftest import (
    V1_KEY,
    V1_OLDER_KEY,
    V2_KEY,
    entry_by_id,
    payload,
    read_backup,
    read_catalog,
    run_cli,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
HISTORY_FIELDS = ("title", "description", "views", "likes", "preview")


def migrate(tmp_path, catalog):
    """Write `catalog` as vault `demo`, migrate it, and read the result back."""
    vault = write_vault(tmp_path, catalog)
    result = run_cli("migrate", "demo", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return vault, read_catalog(vault)


# `migrate` Command: "Syntax | `python mvault.py migrate <name>`".
def test_migrate_takes_a_vault_name(tmp_path):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry("e1")]))
    assert catalog["version"] == 3


# `migrate` Command: "Input | Existing vault with v1, v2, or v3 catalog" and
# "Effect on v1 or v2 | Convert catalog to v3 on disk".
@pytest.mark.parametrize(
    "catalog",
    [v1_catalog([v1_entry("e1")]), v2_catalog("https://example.com/feed", [v2_entry("e1")])],
    ids=["v1", "v2"],
)
def test_migrate_converts_legacy_catalogs_on_disk(tmp_path, catalog):
    _, migrated = migrate(tmp_path, catalog)
    assert migrated["version"] == 3


# `migrate` Command: "Effect on v3 | No-op; no backup written".
def test_migrate_on_a_v3_vault_is_a_no_op(vault):
    before = (vault / "catalog.json").read_bytes()
    result = run_cli("migrate", "demo", cwd=vault.parent)

    assert result.returncode == 0, result.stderr
    assert (vault / "catalog.json").read_bytes() == before
    assert not (vault / "catalog.bak").exists()


# `migrate` Command: "Missing vault | Error to stderr including `<name>`; exit
# non-zero".
def test_migrate_on_a_missing_vault_reports_the_name(tmp_path):
    result = run_cli("migrate", "absent", cwd=tmp_path)
    assert result.returncode != 0
    assert "absent" in result.stderr
    assert result.stdout == ""


# v1-to-v3: "`source_id` | Convert to `source` using
# `https://media.example.com/channel/<source_id>`".
def test_v1_source_id_becomes_a_derived_source_url(tmp_path):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry("e1")], source_id="abc123"))
    assert catalog["source"] == "https://media.example.com/channel/abc123"
    assert "source_id" not in catalog


# v1-to-v3: "Entries | Move every object from `entries` to `episodes`".
def test_v1_entries_move_to_episodes(tmp_path):
    entries = [v1_entry("e1"), v1_entry("e2"), v1_entry("e3")]
    _, catalog = migrate(tmp_path, v1_catalog(entries))

    assert sorted(e["id"] for e in catalog["episodes"]) == ["e1", "e2", "e3"]
    assert "entries" not in catalog


# v1-to-v3: "Missing categories | Create empty `streams` and `clips` arrays".
def test_v1_migration_creates_the_missing_categories(tmp_path):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry("e1")]))
    assert catalog["streams"] == []
    assert catalog["clips"] == []


# v1-to-v3: "History keys | Convert every UNIX-epoch string key to ISO 8601
# format", for every history field of the entry.
def test_v1_history_keys_become_iso_8601(tmp_path):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry("e1")]))
    entry = entry_by_id(catalog, "episodes", "e1")

    for field in HISTORY_FIELDS:
        assert list(entry[field]) == ["2024-06-15T09:40:00"]


# v1-to-v3: "History keys ... ISO 8601 format" — values are carried over
# unchanged, key by key, when a history holds several points.
def test_v1_history_values_survive_key_conversion(tmp_path):
    entry = v1_entry("e1")
    entry["views"] = {V1_OLDER_KEY: 10, V1_KEY: 25}
    _, catalog = migrate(tmp_path, v1_catalog([entry]))

    assert entry_by_id(catalog, "episodes", "e1")["views"] == {
        "2023-11-14T22:13:20": 10,
        "2024-06-15T09:40:00": 25,
    }


# Version 1 UNIX-Epoch History Keys: "Chronological ordering is determined by
# numeric comparison of these values" — `"999999999"` is later than
# `"1718444400"` as text but earlier as a number, and the converted keys order
# the other way round.
def test_v1_key_order_follows_numeric_comparison(tmp_path):
    entry = v1_entry("e1")
    entry["title"] = {"999999999": "older", "1718444400": "newer"}
    _, catalog = migrate(tmp_path, v1_catalog([entry]))
    history = entry_by_id(catalog, "episodes", "e1")["title"]

    assert history == {"2001-09-09T01:46:39": "older", "2024-06-15T09:40:00": "newer"}
    assert history[max(history)] == "newer"


# v1-to-v3: "`removed` | Add `{<migration-timestamp>: false}` to every entry"
# and "`annotations` | Add `[]` to every entry".
def test_v1_entries_gain_removed_and_annotations(tmp_path):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry("e1"), v1_entry("e2")]))

    for entry in catalog["episodes"]:
        assert list(entry["removed"].values()) == [False]
        assert entry["annotations"] == []


# v1-to-v3: "Version field | Set `version` to `3`", and the static fields of
# each entry come through untouched.
def test_v1_migration_keeps_static_entry_fields(tmp_path):
    entry = v1_entry("e1", published="2022-02-02T02:02:02", width=640, height=480)
    _, catalog = migrate(tmp_path, v1_catalog([entry]))
    migrated = entry_by_id(catalog, "episodes", "e1")

    assert catalog["version"] == 3
    assert (migrated["published"], migrated["width"], migrated["height"]) == (
        "2022-02-02T02:02:02",
        640,
        480,
    )


# v2-to-v3: "`source` | Preserve existing value".
def test_v2_source_is_preserved(tmp_path):
    url = "https://videos.example.org/feed.json"
    _, catalog = migrate(tmp_path, v2_catalog(url, [v2_entry("e1")]))
    assert catalog["source"] == url


# v2-to-v3: "Categories | Preserve `episodes`, `streams`, and `clips`
# placement".
def test_v2_category_placement_is_preserved(tmp_path):
    _, catalog = migrate(
        tmp_path,
        v2_catalog(
            "https://example.com/feed",
            episodes=[v2_entry("ep")],
            streams=[v2_entry("st")],
            clips=[v2_entry("cl")],
        ),
    )
    assert [e["id"] for e in catalog["episodes"]] == ["ep"]
    assert [e["id"] for e in catalog["streams"]] == ["st"]
    assert [e["id"] for e in catalog["clips"]] == ["cl"]


# v2-to-v3: "`removed` | Add `{<migration-timestamp>: false}` to every entry in
# every category" and "`annotations` | Add `[]` to every entry".
def test_v2_entries_in_every_category_gain_removed_and_annotations(tmp_path):
    _, catalog = migrate(
        tmp_path,
        v2_catalog(
            "https://example.com/feed",
            episodes=[v2_entry("ep")],
            streams=[v2_entry("st")],
            clips=[v2_entry("cl")],
        ),
    )
    for category in ("episodes", "streams", "clips"):
        entry = catalog[category][0]
        assert list(entry["removed"].values()) == [False]
        assert entry["annotations"] == []


# v2-to-v3: "Version field | Set `version` to `3`"; v2 history keys are already
# ISO 8601 and are carried over unchanged.
def test_v2_history_keys_are_carried_over(tmp_path):
    _, catalog = migrate(tmp_path, v2_catalog("https://example.com/f", [v2_entry("e1")]))
    entry = entry_by_id(catalog, "episodes", "e1")

    assert catalog["version"] == 3
    for field in HISTORY_FIELDS:
        assert list(entry[field]) == [V2_KEY]


# Migration Persistence: "Backup timing | Copy original `catalog.json` to
# `catalog.bak` before migration write" and "Backup content | Semantically
# equivalent pre-migration JSON snapshot".
@pytest.mark.parametrize(
    "catalog",
    [v1_catalog([v1_entry("e1")]), v2_catalog("https://example.com/f", [v2_entry("e1")])],
    ids=["v1", "v2"],
)
def test_migration_backs_up_the_original_catalog(tmp_path, catalog):
    vault, _ = migrate(tmp_path, catalog)
    assert read_backup(vault) == catalog


# Migration Persistence: "Save timing | Save migrated v3 catalog immediately" —
# the converted catalog is on disk when the command returns.
def test_migrated_catalog_is_saved_immediately(tmp_path):
    vault, _ = migrate(tmp_path, v1_catalog([v1_entry("e1")]))
    assert read_catalog(vault)["version"] == 3


# Migration Persistence: "Post-migration usability | All subsequent commands
# operate as for a vault created in v3".
def test_migrated_vault_syncs_like_a_v3_vault(tmp_path, source):
    vault, _ = migrate(tmp_path, v2_catalog(source.url, [v2_entry("e1")]))
    source.serve(payload(episodes=[source_entry("e1", title="renamed")]))
    assert run_cli("sync", "demo", cwd=tmp_path).returncode == 0

    entry = entry_by_id(read_catalog(vault), "episodes", "e1")
    assert entry["title"][max(entry["title"])] == "renamed"
    assert entry["removed"][max(entry["removed"])] is False


# Migration Determinism: "Migration-added `removed` value | Single history
# entry with value `false`".
def test_migration_removed_history_holds_one_false(tmp_path):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry("e1")]))
    removed = entry_by_id(catalog, "episodes", "e1")["removed"]

    assert len(removed) == 1
    assert list(removed.values()) == [False]


# Migration Determinism: "Migration-added timestamp scope | Each
# migration-added `removed` timestamp must be ISO 8601; cross-entry equality is
# not required".
def test_migration_removed_timestamps_are_iso_8601(tmp_path):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry("e1"), v1_entry("e2")]))

    for entry in catalog["episodes"]:
        assert TIMESTAMP.match(next(iter(entry["removed"])))


# Migration Determinism: "v1 UNIX-epoch conversion | Convert each epoch-seconds
# key to `YYYY-MM-DDTHH:MM:SS` in UTC".
@pytest.mark.parametrize(
    "epoch,expected",
    [
        ("0", "1970-01-01T00:00:00"),
        ("1000000000", "2001-09-09T01:46:40"),
        ("1718444400", "2024-06-15T09:40:00"),
    ],
    ids=["epoch-zero", "round-billion", "recent"],
)
def test_v1_epoch_keys_convert_in_utc(tmp_path, epoch, expected):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry("e1", key=epoch)]))
    assert list(entry_by_id(catalog, "episodes", "e1")["title"]) == [expected]


# Migration Determinism: "v1 category target | Every migrated entry goes to
# `episodes`".
def test_every_v1_entry_lands_in_episodes(tmp_path):
    _, catalog = migrate(tmp_path, v1_catalog([v1_entry(f"e{n}") for n in range(5)]))

    assert len(catalog["episodes"]) == 5
    assert catalog["streams"] == [] and catalog["clips"] == []


# Migration Determinism: "v3 reload | No additional history entry, no semantic
# modification, no backup write".
def test_reloading_a_v3_catalog_changes_nothing(tmp_path, source):
    vault, migrated = migrate(tmp_path, v2_catalog(source.url, [v2_entry("e1")]))
    (vault / "catalog.bak").unlink()

    assert run_cli("migrate", "demo", cwd=tmp_path).returncode == 0
    assert read_catalog(vault) == migrated
    assert not (vault / "catalog.bak").exists()


# Migration Determinism: "Idempotence | Re-loading already migrated v3 catalog
# produces no further effects".
def test_migration_is_idempotent(tmp_path):
    vault, first = migrate(tmp_path, v1_catalog([v1_entry("e1")]))
    for _ in range(2):
        assert run_cli("migrate", "demo", cwd=tmp_path).returncode == 0
    assert read_catalog(vault) == first
