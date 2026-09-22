"""Spec sections: `catalog.json` Ordering / `catalog.json` Persistence."""

from __future__ import annotations

import json


# Spec: Ordering | `1` | Newest `published` first |
def test_entries_sorted_newest_published_first(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("old", published="2020-01-01T00:00:00"),
        helpers.make_source_entry("new", published="2024-12-31T23:59:59"),
        helpers.make_source_entry("mid", published="2022-06-15T12:00:00"),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["new", "mid", "old"]


# Spec: Ordering | `2` | Lexicographically smaller `id` first when `published` values are equal |
def test_equal_published_sorted_by_id_ascending(run_cli, vault, source, helpers, workdir):
    same = "2024-01-01T10:00:00"
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("charlie", published=same),
        helpers.make_source_entry("alpha", published=same),
        helpers.make_source_entry("bravo", published=same),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["alpha", "bravo", "charlie"]


# Spec: Ordering | `2` | Lexicographically ... | (byte order, not case-insensitive collation)
def test_id_tiebreak_is_lexicographic(run_cli, vault, source, helpers, workdir):
    same = "2024-01-01T10:00:00"
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("a", published=same),
        helpers.make_source_entry("B", published=same),
        helpers.make_source_entry("Z", published=same),
        helpers.make_source_entry("10", published=same),
        helpers.make_source_entry("2", published=same),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    ids = [e["id"] for e in catalog["episodes"]]
    assert ids == sorted(ids)
    assert ids == ["10", "2", "B", "Z", "a"]


# Spec: Ordering applies to each category array.
def test_ordering_applies_to_every_category(run_cli, vault, source, helpers, workdir):
    entries = [
        helpers.make_source_entry("b", published="2021-01-01T00:00:00"),
        helpers.make_source_entry("a", published="2023-01-01T00:00:00"),
    ]
    source.set(helpers.make_payload(episodes=entries, streams=entries, clips=entries))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    for category in ("episodes", "streams", "clips"):
        assert [e["id"] for e in catalog[category]] == ["a", "b"], category


# Spec: Ordering | ... | (order is maintained when entries are added later)
def test_ordering_maintained_after_later_sync(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("mid", published="2022-01-01T00:00:00")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("mid", published="2022-01-01T00:00:00"),
        helpers.make_source_entry("newest", published="2025-01-01T00:00:00"),
        helpers.make_source_entry("oldest", published="2019-01-01T00:00:00"),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["newest", "mid", "oldest"]


# Spec: Ordering | ... | (removed entries keep their place in the ordering)
def test_removed_entries_participate_in_ordering(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("a", published="2024-01-01T00:00:00"),
        helpers.make_source_entry("b", published="2023-01-01T00:00:00"),
        helpers.make_source_entry("c", published="2022-01-01T00:00:00"),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("a", published="2024-01-01T00:00:00"),
        helpers.make_source_entry("c", published="2022-01-01T00:00:00"),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["a", "b", "c"]


# Spec: Ordering compares normalized published values (date-only sorts at 00:00:00).
def test_date_only_published_orders_by_normalized_value(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("dateonly", published="2024-03-02"),
        helpers.make_source_entry("earlier_same_day", published="2024-03-02T00:00:00"),
        helpers.make_source_entry("later", published="2024-03-02T09:00:00"),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["later", "dateonly", "earlier_same_day"]


# Spec: Persistence | Backup trigger | Before every write to existing `catalog.json` |
#       Persistence | Backup path | `catalog.bak` | (see AMBIGUITIES.md T1)
def test_backup_written_beside_catalog(run_cli, vault, source, helpers):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    assert (vault / "catalog.bak").is_file()


# Spec: Persistence | Backup content | Byte-for-byte copy of pre-write `catalog.json` |
def test_backup_is_byte_for_byte_pre_write_catalog(run_cli, vault, source, helpers):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=1)]))
    assert run_cli("sync", "vault").returncode == 0
    before = (vault / "catalog.json").read_bytes()

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=2)]))
    assert run_cli("sync", "vault").returncode == 0

    assert (vault / "catalog.bak").read_bytes() == before
    assert (vault / "catalog.json").read_bytes() != before


# Spec: Persistence | Backup overwrite | Replace existing `catalog.bak` |
def test_backup_is_replaced_on_each_write(run_cli, vault, source, helpers):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=1)]))
    assert run_cli("sync", "vault").returncode == 0

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=2)]))
    assert run_cli("sync", "vault").returncode == 0
    after_second = (vault / "catalog.json").read_bytes()
    backup_after_second = (vault / "catalog.bak").read_bytes()

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=3)]))
    assert run_cli("sync", "vault").returncode == 0

    backup_after_third = (vault / "catalog.bak").read_bytes()
    assert backup_after_third != backup_after_second
    assert backup_after_third == after_second
    entry = json.loads(backup_after_third.decode("utf-8"))["episodes"][0]
    assert helpers.current(entry["views"]) == 2


# Spec: Persistence | Backup content | ... (pre-existing catalog.bak is replaced, not appended)
def test_existing_backup_content_is_overwritten(run_cli, vault, source, helpers):
    (vault / "catalog.bak").write_text("STALE BACKUP", encoding="utf-8")
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    assert (vault / "catalog.bak").read_text(encoding="utf-8") != "STALE BACKUP"


# Spec: "... leave the vault unchanged" -> a failed sync writes neither catalog nor backup.
def test_failed_sync_does_not_write_backup(run_cli, vault, source):
    source.set_raw("not json")
    assert run_cli("sync", "vault").returncode != 0
    assert not (vault / "catalog.bak").exists()


# Spec: Persistence | Backup trigger | Before every write to *existing* catalog.json |
# Context: `init` creates the catalog where none existed. See AMBIGUITIES.md T2.
def test_init_does_not_create_backup(run_cli, workdir):
    assert run_cli("init", "fresh", "http://example.invalid/f.json").returncode == 0
    assert not (workdir / "fresh" / "catalog.bak").exists()


# Spec: Persistence: the written catalog remains valid JSON that the next sync accepts.
def test_written_catalog_round_trips(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert catalog["version"] == 3
    assert catalog["source"] == source.url
    assert run_cli("sync", "vault").returncode == 0
