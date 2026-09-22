"""Spec section: `catalog.json` Persistence."""

from conftest import payload, read_catalog, source_entry


# Spec: Backup trigger | Before every write to existing `catalog.json`
def test_sync_creates_backup(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    assert (vault / "catalog.bak").is_file()


# Spec: Backup path | `catalog.bak`
def test_backup_lives_beside_the_catalog(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    assert {p.name for p in vault.iterdir()} == {"catalog.json", "catalog.bak"}


# Spec: Backup content | Byte-for-byte copy of pre-write `catalog.json`
def test_backup_is_a_byte_for_byte_copy_of_the_previous_catalog(run, source, vault):
    before = (vault / "catalog.json").read_bytes()
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    assert (vault / "catalog.bak").read_bytes() == before


# Spec: Backup overwrite | Replace existing `catalog.bak`
def test_backup_is_replaced_on_each_sync(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", views=1)]))
    run("sync", "vault")
    after_first = (vault / "catalog.json").read_bytes()

    source.serve(payload(episodes=[source_entry("e1", views=2)]))
    run("sync", "vault")
    assert (vault / "catalog.bak").read_bytes() == after_first


# Spec: Backup trigger | Before every write (init has no existing catalog to back up)
def test_init_writes_no_backup(run, vault):
    assert not (vault / "catalog.bak").exists()


# Spec: Backup trigger | Before every write (T2: sync always writes)
def test_no_change_sync_still_refreshes_the_backup(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    after_first = (vault / "catalog.json").read_bytes()

    run("sync", "vault")
    assert (vault / "catalog.bak").read_bytes() == after_first


# Spec: Backup content ... (a failed sync writes neither catalog nor backup)
def test_failed_sync_leaves_catalog_and_backup_untouched(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    catalog_bytes = (vault / "catalog.json").read_bytes()
    backup_bytes = (vault / "catalog.bak").read_bytes()

    source.serve_raw("not json")
    assert run("sync", "vault").returncode != 0
    assert (vault / "catalog.json").read_bytes() == catalog_bytes
    assert (vault / "catalog.bak").read_bytes() == backup_bytes


# Spec: Backup content | Byte-for-byte copy (backup is valid, parseable JSON)
def test_backup_parses_as_the_previous_catalog_state(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", title="first")]))
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("e1", title="second")]))
    run("sync", "vault")

    import json

    backup = json.loads((vault / "catalog.bak").read_text())
    history = backup["episodes"][0]["title"]
    assert history[max(history)] == "first"
    assert read_catalog(vault)["episodes"][0]["title"][
        max(read_catalog(vault)["episodes"][0]["title"])
    ] == "second"
