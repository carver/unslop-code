"""Spec section: Migration Determinism."""

from conftest import (
    TIMESTAMP_RE,
    all_entries,
    migrated,
    payload,
    read_catalog,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)


# Spec: Migration-added `removed` value | Single history entry with value `false`
def test_removed_history_has_exactly_one_false_entry(run, tmp_path):
    catalog = migrated(
        run, tmp_path, v2_catalog(episodes=[v2_entry("e1")], clips=[v2_entry("c1")])
    )

    for entry in all_entries(catalog):
        assert list(entry["removed"].values()) == [False]


# Spec: Migration-added timestamp scope | Each migration-added `removed` timestamp must be
# ISO 8601; cross-entry equality is not required
def test_every_migration_timestamp_is_iso_8601(run, tmp_path):
    entries = [v1_entry("e1"), v1_entry("e2"), v1_entry("e3")]
    catalog = migrated(run, tmp_path, v1_catalog(entries=entries))

    for entry in catalog["episodes"]:
        stamp, = entry["removed"]
        assert TIMESTAMP_RE.match(stamp), stamp


# Spec: v1 category target | Every migrated entry goes to `episodes`
def test_no_migrated_v1_entry_lands_outside_episodes(run, tmp_path):
    entries = [v1_entry("e1"), v1_entry("e2")]
    catalog = migrated(run, tmp_path, v1_catalog(entries=entries))

    assert len(catalog["episodes"]) == 2
    assert catalog["streams"] == [] and catalog["clips"] == []


# Spec: v3 reload | No additional history entry, no semantic modification, no backup write
def test_reloading_a_v3_catalog_adds_no_history(run, tmp_path, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    before = read_catalog(vault)

    assert run("migrate", "vault").returncode == 0
    assert read_catalog(vault) == before


# Spec: v3 reload | ... no backup write
def test_reloading_a_v3_catalog_writes_no_backup(run, tmp_path):
    directory = write_vault(
        tmp_path,
        {
            "version": 3,
            "source": "http://example.invalid/source.json",
            "episodes": [],
            "streams": [],
            "clips": [],
        },
    )

    assert run("migrate", "vault").returncode == 0
    assert not (directory / "catalog.bak").exists()


# Spec: Idempotence | Re-loading already migrated v3 catalog produces no further effects
def test_migration_is_idempotent(run, tmp_path):
    first = migrated(run, tmp_path, v1_catalog(entries=[v1_entry("e1")]))

    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path / "vault") == first


# Spec: Idempotence | ... (a migrated vault keeps its shape across a later sync)
def test_migrated_entries_keep_their_added_fields_after_sync(run, tmp_path, source):
    directory = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=source.url))
    run("migrate", "vault")
    source.serve(payload(episodes=[source_entry("e1", views=42)]))
    run("sync", "vault")

    entry = read_catalog(directory)["episodes"][0]
    assert entry["annotations"] == []
    assert list(entry["removed"].values()) == [False]
