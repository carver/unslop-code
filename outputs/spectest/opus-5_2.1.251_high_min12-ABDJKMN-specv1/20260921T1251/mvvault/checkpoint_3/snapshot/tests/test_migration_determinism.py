"""Spec section: Migration Determinism."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
CATEGORIES = ("episodes", "streams", "clips")


def catalog_path(workdir, name="vault"):
    return Path(workdir) / name / "catalog.json"


def backup_path(workdir, name="vault"):
    return Path(workdir) / name / "catalog.bak"


# Spec: | Migration-added `removed` value | Single history entry with value `false` |
def test_migration_removed_is_a_single_false_entry(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    removed = helpers.find_entry(helpers.read_catalog(workdir), "e1")["removed"]
    assert len(removed) == 1
    value = next(iter(removed.values()))
    assert value is False


# Spec: | Migration-added timestamp scope | Each migration-added `removed`
#       timestamp must be ISO 8601; cross-entry equality is not required |
def test_migration_timestamps_are_iso_8601(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v2_catalog(
        episodes=[legacy.v2_entry("e1"), legacy.v2_entry("e2")],
        streams=[legacy.v2_entry("s1")]))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    stamps = [next(iter(e["removed"])) for c in CATEGORIES for e in catalog[c]]
    assert len(stamps) == 3
    for stamp in stamps:
        assert ISO_RE.match(stamp), stamp
        assert datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S")


# Spec: | Migration-added timestamp scope | ... ISO 8601 ... |
# Context: the timestamp reflects the migration run, i.e. "now".
def test_migration_timestamp_is_recent(run_cli, make_vault, legacy, helpers, workdir):
    before = datetime.now().replace(microsecond=0)
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    after = datetime.now().replace(microsecond=0)
    stamp = next(iter(helpers.find_entry(helpers.read_catalog(workdir), "e1")["removed"]))
    parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S")
    assert before <= parsed <= after


# Spec: | v1 UNIX-epoch conversion | Convert each epoch-seconds key to
#       `YYYY-MM-DDTHH:MM:SS` in UTC |
@pytest.mark.parametrize("epoch,iso", [
    ("1718444400", "2024-06-15T09:40:00"),
    ("0", "1970-01-01T00:00:00"),
    ("1000000000", "2001-09-09T01:46:40"),
    ("1700000000", "2023-11-14T22:13:20"),
])
def test_v1_epoch_converted_in_utc(run_cli, make_vault, legacy, helpers, workdir, epoch, iso):
    assert datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S") == iso
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1", epoch=epoch)]))
    assert run_cli("migrate", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert list(entry["title"]) == [iso]


# Spec: | v1 UNIX-epoch conversion | ... `YYYY-MM-DDTHH:MM:SS` ... |
# Context: no timezone suffix survives the conversion.
def test_v1_converted_keys_have_no_suffix(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in ("title", "description", "views", "likes", "preview", "removed"):
        for key in entry[field]:
            assert ISO_RE.match(key), key
            assert not key.endswith("Z") and "+" not in key


# Spec: | v1 category target | Every migrated entry goes to `episodes` |
def test_v1_every_entry_goes_to_episodes(run_cli, make_vault, legacy, helpers, workdir):
    entries = [legacy.v1_entry(f"e{i}") for i in range(5)]
    make_vault(legacy.v1_catalog(entries=entries))
    assert run_cli("migrate", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert len(catalog["episodes"]) == 5
    assert catalog["streams"] == [] and catalog["clips"] == []


# Spec: | v1 `source_id` conversion | `https://media.example.com/channel/<source_id>` |
@pytest.mark.parametrize("source_id", ["chan-1", "UPPER", "a.b_c"])
def test_v1_source_id_conversion_is_literal(run_cli, make_vault, legacy, helpers, workdir, source_id):
    make_vault(legacy.v1_catalog(source_id=source_id))
    assert run_cli("migrate", "vault").returncode == 0
    assert helpers.read_catalog(workdir)["source"] == (
        f"https://media.example.com/channel/{source_id}")


# Spec: | v3 reload | No additional history entry, no semantic modification,
#       no backup write |
def test_v3_reload_adds_no_history_and_no_backup(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    migrated = json.loads(catalog_path(workdir).read_text(encoding="utf-8"))
    backup = backup_path(workdir).read_text(encoding="utf-8")

    assert run_cli("migrate", "vault").returncode == 0
    assert json.loads(catalog_path(workdir).read_text(encoding="utf-8")) == migrated
    assert backup_path(workdir).read_text(encoding="utf-8") == backup


# Spec: | Idempotence | Re-loading already migrated v3 catalog produces no
#       further effects |
def test_migration_is_idempotent(run_cli, make_vault, legacy, workdir):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    first = catalog_path(workdir).read_text(encoding="utf-8")
    for _ in range(3):
        assert run_cli("migrate", "vault").returncode == 0
        assert catalog_path(workdir).read_text(encoding="utf-8") == first


# Spec: | Idempotence | ... no further effects |
# Context: a second migration must not append another `removed` history entry.
def test_second_migration_adds_no_removed_entry(run_cli, make_vault, legacy, helpers, workdir):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    assert run_cli("migrate", "vault").returncode == 0
    assert run_cli("migrate", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert len(entry["removed"]) == 1
    assert entry["annotations"] == []


# Spec: | v3 reload | ... no semantic modification ... |
# Context: local-only `annotations` content already on a v3 entry is preserved.
def test_v3_reload_preserves_existing_annotations(run_cli, make_vault, legacy, helpers, workdir, source):
    catalog = legacy.v2_catalog(episodes=[legacy.v2_entry("e1")])
    catalog["version"] = 3
    catalog["episodes"][0]["removed"] = {"2024-06-15T09:40:00": False}
    catalog["episodes"][0]["annotations"] = ["keep me"]
    make_vault(catalog)
    assert run_cli("migrate", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["annotations"] == ["keep me"]
    assert entry["removed"] == {"2024-06-15T09:40:00": False}
