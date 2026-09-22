"""`catalog.json` Ordering and `catalog.json` Persistence."""

import json

from conftest import read_catalog, source_entry


def sync(run_cli, source, episodes=(), streams=(), clips=()):
    source.payload = {"episodes": list(episodes), "streams": list(streams), "clips": list(clips)}
    result = run_cli("sync", "v")
    assert result.returncode == 0, result.stderr


# Spec: Sort Key Priority 1 | Newest `published` first
def test_entries_sorted_newest_published_first(run_cli, vault, source):
    sync(
        run_cli,
        source,
        episodes=[
            source_entry("old", published="2020-01-01T00:00:00"),
            source_entry("new", published="2024-06-01T00:00:00"),
            source_entry("mid", published="2022-03-05T00:00:00"),
        ],
    )
    assert [e["id"] for e in read_catalog(vault)["episodes"]] == ["new", "mid", "old"]


# Spec: Sort Key Priority 2 | Lexicographically smaller `id` first when `published`
# values are equal
def test_ties_break_on_lexicographic_id(run_cli, vault, source):
    same = "2024-01-01T00:00:00"
    sync(
        run_cli,
        source,
        episodes=[source_entry("b", published=same), source_entry("A", published=same), source_entry("a", published=same)],
    )
    assert [e["id"] for e in read_catalog(vault)["episodes"]] == ["A", "a", "b"]


# Spec: Entry order ... applies to every category
def test_ordering_applies_to_every_category(run_cli, vault, source):
    rows = [source_entry("z", published="2020-01-01"), source_entry("y", published="2023-01-01")]
    sync(run_cli, source, episodes=rows, streams=rows, clips=rows)
    catalog = read_catalog(vault)
    for name in ("episodes", "streams", "clips"):
        assert [e["id"] for e in catalog[name]] == ["y", "z"]


# Spec: Newest `published` first (ordering mixes date-only and datetime values)
def test_ordering_compares_normalized_published(run_cli, vault, source):
    sync(
        run_cli,
        source,
        episodes=[
            source_entry("dateonly", published="2024-01-02"),
            source_entry("earlier", published="2024-01-01T23:59:59"),
        ],
    )
    assert [e["id"] for e in read_catalog(vault)["episodes"]] == ["dateonly", "earlier"]


# Spec: Newest `published` first (order is maintained when entries are added later)
def test_ordering_is_reapplied_on_later_syncs(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("old", published="2020-01-01")])
    sync(
        run_cli,
        source,
        episodes=[source_entry("old", published="2020-01-01"), source_entry("new", published="2025-01-01")],
    )
    assert [e["id"] for e in read_catalog(vault)["episodes"]] == ["new", "old"]


# Spec: Removal handling | Never delete entry (removed entries stay in sort order)
def test_removed_entries_keep_their_place_in_order(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("old", published="2020-01-01"), source_entry("new", published="2025-01-01")])
    sync(run_cli, source, episodes=[source_entry("old", published="2020-01-01")])
    assert [e["id"] for e in read_catalog(vault)["episodes"]] == ["new", "old"]


# Spec: Backup trigger | Before every write to existing `catalog.json`
# Spec: Backup path | `catalog.bak`
def test_sync_writes_backup_next_to_catalog(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    assert (vault / "catalog.bak").is_file()


# Spec: Backup content | Byte-for-byte copy of pre-write `catalog.json`
def test_backup_is_byte_for_byte_pre_write_catalog(run_cli, vault, source):
    before = (vault / "catalog.json").read_bytes()
    sync(run_cli, source, episodes=[source_entry("a")])
    assert (vault / "catalog.bak").read_bytes() == before


# Spec: Backup overwrite | Replace existing `catalog.bak`
def test_backup_is_replaced_on_each_write(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", views=1)])
    after_first = (vault / "catalog.json").read_bytes()
    sync(run_cli, source, episodes=[source_entry("a", views=2)])
    assert (vault / "catalog.bak").read_bytes() == after_first


# Spec: Success effect | Create new vault with empty catalog (no pre-write file to copy)
def test_init_creates_no_backup(run_cli, tmp_path):
    run_cli("init", "fresh", "http://example.invalid/f.json")
    assert not (tmp_path / "fresh" / "catalog.bak").exists()


# Spec: Backup trigger | Before every write (a failed sync writes nothing at all)
def test_failed_sync_writes_no_backup(run_cli, vault, source):
    source.status = 503
    run_cli("sync", "v")
    assert not (vault / "catalog.bak").exists()


# Spec: `catalog.json` Root Schema (the file stays valid JSON with the root schema)
def test_catalog_keeps_root_schema_after_sync(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert catalog["source"] == source.url
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}
