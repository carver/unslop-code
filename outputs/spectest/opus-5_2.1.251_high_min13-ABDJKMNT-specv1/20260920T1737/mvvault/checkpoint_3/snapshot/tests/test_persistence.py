"""Spec section: `catalog.json` Persistence / `mvault` Error Handling summary."""

from conftest import read_catalog, source_entry

FETCH_FAILURE = "Source metadata fetch failure"


def sync(run_cli):
    result = run_cli("sync", "demo")
    assert result.returncode == 0, result.stderr


# Phrase: "Backup trigger | Before every write to existing `catalog.json`" - init has no existing file
def test_init_creates_no_backup(run_cli, tmp_path):
    run_cli("init", "demo", "http://example.test/feed.json")
    assert not (tmp_path / "demo" / "catalog.bak").exists()


# Phrase: "Backup path | `catalog.bak`" (see AMBIGUITIES T1)
def test_sync_writes_backup_inside_vault(run_cli, source, vault, tmp_path):
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)
    assert (vault / "catalog.bak").is_file()
    assert not (tmp_path / "catalog.bak").exists()


# Phrase: "Backup content | Byte-for-byte copy of pre-write `catalog.json`"
def test_backup_is_byte_for_byte_copy_of_pre_write_catalog(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", title="first")])
    sync(run_cli)
    pre_write = (vault / "catalog.json").read_bytes()

    source.serve(episodes=[source_entry("e1", title="second")])
    sync(run_cli)

    assert (vault / "catalog.bak").read_bytes() == pre_write
    assert (vault / "catalog.json").read_bytes() != pre_write


# Phrase: "Backup overwrite | Replace existing `catalog.bak`"
def test_backup_is_replaced_on_each_write(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", views=1)])
    sync(run_cli)
    source.serve(episodes=[source_entry("e1", views=2)])
    sync(run_cli)
    second_pre_write = (vault / "catalog.json").read_bytes()
    source.serve(episodes=[source_entry("e1", views=3)])
    sync(run_cli)

    assert (vault / "catalog.bak").read_bytes() == second_pre_write


# Phrase: "Backup content | Byte-for-byte copy" - the backup parses as the previous catalog
def test_backup_holds_previous_catalog_state(run_cli, source, vault):
    import json

    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)
    source.serve(episodes=[source_entry("e1"), source_entry("e2")])
    sync(run_cli)

    backup = json.loads((vault / "catalog.bak").read_text())
    assert [entry["id"] for entry in backup["episodes"]] == ["e1"]
    assert len(read_catalog(vault)["episodes"]) == 2


# Phrase: "leave the vault unchanged" - a failed fetch performs no write and no backup
def test_failed_sync_writes_nothing(run_cli, source, vault):
    source.raw_body = b"not json"
    result = run_cli("sync", "demo")
    assert result.returncode != 0
    assert FETCH_FAILURE in result.stderr
    assert not (vault / "catalog.bak").exists()


# Phrase: "`catalog.json` Root Schema" - the root shape survives syncing
def test_root_schema_is_preserved_after_sync(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert catalog["source"] == source.url
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Phrase: "Success effect | Update catalog with new, changed, removed, and restored entries"
def test_successful_sync_exits_zero_and_is_quiet_on_stderr(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    result = run_cli("sync", "demo")
    assert result.returncode == 0
    assert result.stderr == ""


# Phrase: "`sync` with non-existent vault | stderr | non-zero | Message includes vault name"
def test_sync_errors_go_to_stderr_only(run_cli):
    result = run_cli("sync", "nope")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "nope" in result.stderr


# Phrase: "Locale | No locale-sensitive formatting anywhere"
def test_output_is_locale_independent(run_cli, source, vault, tmp_path):
    import json

    source.serve(episodes=[source_entry("e1", views=1234567)])
    sync(run_cli)
    catalog = read_catalog(vault)
    assert catalog["episodes"][0]["views"][next(iter(catalog["episodes"][0]["views"]))] == 1234567
    assert "," not in json.dumps(catalog["episodes"][0]["views"])
