"""Spec sections: `catalog.json` Ordering / `catalog.json` Persistence."""

import json

from conftest import payload, read_catalog, run_cli, source_entry


def sync_with(vault, source, episodes=(), streams=(), clips=()):
    source.serve(payload(episodes, streams, clips))
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode == 0, result.stderr
    return read_catalog(vault)


# Ordering: "`1` | Newest `published` first".
def test_entries_are_ordered_newest_published_first(vault, source):
    catalog = sync_with(
        vault,
        source,
        episodes=[
            source_entry("mid", published="2022-06-01T00:00:00"),
            source_entry("old", published="2020-01-01T00:00:00"),
            source_entry("new", published="2024-12-31T23:59:59"),
        ],
    )
    assert [e["id"] for e in catalog["episodes"]] == ["new", "mid", "old"]


# Ordering: "`2` | Lexicographically smaller `id` first when `published` values
# are equal".
def test_equal_published_ties_break_on_id(vault, source):
    same = "2023-03-03T03:03:03"
    catalog = sync_with(
        vault,
        source,
        clips=[
            source_entry("b", published=same),
            source_entry("C", published=same),
            source_entry("a", published=same),
        ],
    )
    assert [e["id"] for e in catalog["clips"]] == ["C", "a", "b"]


# Ordering: both keys together, and applied per category.
def test_ordering_applies_within_each_category(vault, source):
    catalog = sync_with(
        vault,
        source,
        episodes=[
            source_entry("e2", published="2021-01-01T00:00:00"),
            source_entry("e1", published="2021-01-01T00:00:00"),
            source_entry("e3", published="2022-01-01T00:00:00"),
        ],
        streams=[
            source_entry("s1", published="2019-01-01T00:00:00"),
            source_entry("s2", published="2025-01-01T00:00:00"),
        ],
    )
    assert [e["id"] for e in catalog["episodes"]] == ["e3", "e1", "e2"]
    assert [e["id"] for e in catalog["streams"]] == ["s2", "s1"]


# Ordering: order is maintained as later syncs add entries, and removed entries
# keep their place in the ordering.
def test_ordering_is_maintained_across_syncs(vault, source):
    sync_with(vault, source, episodes=[source_entry("b", published="2022-01-01T00:00:00")])
    catalog = sync_with(
        vault,
        source,
        episodes=[
            source_entry("c", published="2021-01-01T00:00:00"),
            source_entry("a", published="2023-01-01T00:00:00"),
        ],
    )
    assert [e["id"] for e in catalog["episodes"]] == ["a", "b", "c"]


# Persistence: "Backup trigger | Before every write to existing `catalog.json`"
# and "Backup path | `catalog.bak`".
def test_sync_writes_the_backup_beside_the_catalog(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    assert (vault / "catalog.bak").is_file()


# Persistence: "Backup content | Byte-for-byte copy of pre-write
# `catalog.json`" — the first sync backs up the freshly initialised catalog.
def test_backup_holds_the_pre_write_bytes(vault, source):
    before = (vault / "catalog.json").read_bytes()
    sync_with(vault, source, episodes=[source_entry("e1")])
    assert (vault / "catalog.bak").read_bytes() == before


# Persistence: "Backup overwrite | Replace existing `catalog.bak`" — the second
# sync's backup is the catalog the first sync wrote.
def test_backup_is_replaced_on_each_write(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    after_first = (vault / "catalog.json").read_bytes()

    sync_with(vault, source, episodes=[source_entry("e1", views=77)])

    assert (vault / "catalog.bak").read_bytes() == after_first
    assert (vault / "catalog.json").read_bytes() != after_first


# Persistence: "Backup trigger | Before every write" — a sync that changes
# nothing still rewrites the catalog and refreshes the backup
# (see AMBIGUITIES T2).
def test_no_op_sync_still_refreshes_the_backup(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    after_first = (vault / "catalog.json").read_bytes()

    sync_with(vault, source, episodes=[source_entry("e1")])

    assert (vault / "catalog.bak").read_bytes() == after_first


# Persistence: `init` creates a catalog where none existed, so it has nothing
# to back up.
def test_init_writes_no_backup(tmp_path):
    run_cli("init", "demo", "http://example.invalid/f.json", cwd=tmp_path)
    assert not (tmp_path / "demo" / "catalog.bak").exists()


# Persistence: a failed sync neither writes the catalog nor the backup.
def test_failed_sync_does_not_touch_the_backup(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    backup = (vault / "catalog.bak").read_bytes()

    source.serve_raw("not json at all")
    assert run_cli("sync", "demo", cwd=vault.parent).returncode != 0

    assert (vault / "catalog.bak").read_bytes() == backup


# Root Schema: the catalog keeps its root fields after a sync.
def test_sync_preserves_root_fields(vault, source):
    catalog = sync_with(vault, source, episodes=[source_entry("e1")])
    assert catalog["version"] == 3
    assert catalog["source"] == source.url
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Persistence: the catalog on disk stays valid JSON that round-trips.
def test_catalog_file_is_valid_json_after_sync(vault, source):
    sync_with(vault, source, episodes=[source_entry("e1")])
    assert isinstance(json.loads((vault / "catalog.json").read_text()), dict)
