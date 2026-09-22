"""Spec section: Version Handling Errors / Supported Versions."""

import json

from conftest import EPOCH_KEY, ISO_KEY, legacy_entry, v1_catalog, v2_catalog, write_vault


def unchanged(vault, original):
    """The catalog still holds the original document and no backup was written."""
    return json.loads((vault / "catalog.json").read_text()) == original and not (vault / "catalog.bak").exists()


# Phrase: "Missing `version` field | Error to stderr; exit non-zero; no migration; no modification"
def test_missing_version_is_rejected(run_cli, tmp_path):
    original = {"source": "http://example.test/feed.json", "episodes": [], "streams": [], "clips": []}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert result.stderr != ""
    assert unchanged(vault, original)


# Phrase: "Non-integer `version` field | Version-related error to stderr; exit non-zero"
def test_string_version_is_a_version_error(run_cli, tmp_path):
    original = {"version": "3", "source": "http://example.test/feed.json", "episodes": [], "streams": [], "clips": []}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(vault, original)


# Phrase: "Non-integer `version` field" - a float is not an integer either
def test_float_version_is_a_version_error(run_cli, tmp_path):
    original = {"version": 2.5, "source": "http://example.test/feed.json", "episodes": []}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(vault, original)


# Phrase: "`version` greater than `3` | Version-related error to stderr; exit non-zero; no migration"
def test_future_version_is_rejected(run_cli, tmp_path):
    original = {"version": 4, "source": "http://example.test/feed.json", "episodes": [], "streams": [], "clips": []}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(vault, original)


# Phrase: "Supported Versions" table lists 1, 2 and 3 only (AMBIGUITIES T15)
def test_version_zero_is_rejected(run_cli, tmp_path):
    original = {"version": 0, "source": "http://example.test/feed.json", "entries": []}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(vault, original)


# Phrase: "`version` greater than `3`" - sync rejects it too, not just `migrate`
def test_sync_rejects_an_unsupported_version(run_cli, source, tmp_path):
    original = {"version": 9, "source": source.url, "episodes": [], "streams": [], "clips": []}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("sync", "legacy")
    assert result.returncode != 0
    assert "version" in result.stderr.lower()
    assert unchanged(vault, original)
    assert source.requests == 0


# Phrase: "Invalid JSON in `catalog.json` | Error to stderr; exit non-zero; no migration"
def test_invalid_json_is_rejected(run_cli, tmp_path):
    vault = write_vault(tmp_path, "legacy", "{not json")
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert "legacy" in result.stderr
    assert (vault / "catalog.json").read_text() == "{not json"
    assert not (vault / "catalog.bak").exists()


# Phrase: "Failure writing `catalog.bak` | Error to stderr; exit non-zero; abort migration;
# leave original `catalog.json` intact"
def test_unwritable_backup_aborts_the_migration(run_cli, tmp_path):
    original = v1_catalog(legacy_entry("e1", EPOCH_KEY))
    vault = write_vault(tmp_path, "legacy", original)
    (vault / "catalog.bak").mkdir()  # a directory cannot be replaced by the backup copy

    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert result.stderr != ""
    assert json.loads((vault / "catalog.json").read_text()) == original


# Phrase: "Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave `catalog.json` unchanged"
def test_v1_entry_missing_a_tracked_field_is_rejected(run_cli, tmp_path):
    entry = legacy_entry("e1", EPOCH_KEY)
    del entry["views"]
    original = v1_catalog(entry)
    vault = write_vault(tmp_path, "legacy", original)

    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert unchanged(vault, original)


# Phrase: "Malformed v1 or v2 entry data" - a v1 key that is not epoch seconds (AMBIGUITIES T20)
def test_v1_entry_with_a_non_epoch_key_is_rejected(run_cli, tmp_path):
    original = v1_catalog(legacy_entry("e1", "not-an-epoch"))
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert unchanged(vault, original)


# Phrase: "Malformed v1 or v2 entry data" - a v2 key that is not ISO 8601
def test_v2_entry_with_a_non_iso_key_is_rejected(run_cli, tmp_path):
    original = v2_catalog("http://example.test/feed.json", episodes=[legacy_entry("e1", "yesterday")])
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert unchanged(vault, original)


# Phrase: "Malformed v1 or v2 entry data" - a mistyped static field
def test_v2_entry_with_a_mistyped_static_field_is_rejected(run_cli, tmp_path):
    original = v2_catalog(
        "http://example.test/feed.json", episodes=[legacy_entry("e1", ISO_KEY, width="wide")]
    )
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert unchanged(vault, original)


# Phrase: "Malformed v1 or v2 entry data" - an entry that is not an object at all
def test_v1_entry_that_is_not_an_object_is_rejected(run_cli, tmp_path):
    original = {"version": 1, "source_id": "chan42", "entries": ["nope"]}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert unchanged(vault, original)


# Phrase: "`source_id` | string | Short platform identifier" - a v1 catalog without one is unusable
def test_v1_catalog_without_source_id_is_rejected(run_cli, tmp_path):
    original = {"version": 1, "entries": []}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert unchanged(vault, original)


# Phrase: "`entries` | array | All entries in a single flat list"
def test_v1_catalog_without_entries_is_rejected(run_cli, tmp_path):
    original = {"version": 1, "source_id": "chan42"}
    vault = write_vault(tmp_path, "legacy", original)
    result = run_cli("migrate", "legacy")
    assert result.returncode != 0
    assert unchanged(vault, original)
