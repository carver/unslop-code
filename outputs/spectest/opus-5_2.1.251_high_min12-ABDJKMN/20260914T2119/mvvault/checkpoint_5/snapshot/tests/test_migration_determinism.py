"""Spec: Migration Determinism."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from conftest import (EPOCH_A, EPOCH_B, ISO_A, ISO_B, MVAULT, TS_RE,
                      V1_SOURCE_PREFIX, backup_path, catalog_bytes,
                      catalog_path, make_entry, make_v1_catalog, make_v1_entry,
                      make_v2_catalog, make_v2_entry, make_v3_catalog,
                      make_v3_entry, read_catalog, read_json)


# Spec: "| Migration-added `removed` value | Single history entry with value
# `false` |"
def test_removed_is_a_single_false_history_entry(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=[make_v1_entry(id="a"),
                                        make_v1_entry(id="b")]))
    run("migrate", "vault")
    for entry in read_catalog(tmp_path)["episodes"]:
        assert len(entry["removed"]) == 1
        assert list(entry["removed"].values()) == [False]


# Spec: "Migration-added `removed` value | Single history entry with value
# `false`" -- the value is the JSON boolean, not a string or 0.
def test_removed_value_is_boolean_false(run, tmp_path, make_vault):
    make_vault(make_v2_catalog())
    run("migrate", "vault")
    value = list(read_catalog(tmp_path)["episodes"][0]["removed"].values())[0]
    assert value is False


# Spec: "| Migration-added timestamp scope | Each migration-added `removed`
# timestamp must be ISO 8601; ... |"
def test_migration_timestamp_is_iso_8601(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=[make_v1_entry(id="a"),
                                        make_v1_entry(id="b")]))
    run("migrate", "vault")
    for entry in read_catalog(tmp_path)["episodes"]:
        (key,) = list(entry["removed"])
        assert TS_RE.match(key), key
        datetime.strptime(key, "%Y-%m-%dT%H:%M:%S")


# Spec: "Migration-added timestamp scope | ... cross-entry equality is **not**
# required |" -- entries may share a timestamp or not, so only the format is
# asserted; here the timestamps must at least all be valid and recent.
def test_cross_entry_timestamps_need_not_match(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=[make_v1_entry(id=str(i))
                                        for i in range(5)]))
    run("migrate", "vault")
    stamps = [list(e["removed"])[0]
              for e in read_catalog(tmp_path)["episodes"]]
    assert len(stamps) == 5
    for stamp in stamps:
        assert TS_RE.match(stamp), stamp


# Spec: "| v1 UNIX-epoch conversion | Convert each epoch-seconds key to
# `YYYY-MM-DDTHH:MM:SS` in UTC |"
@pytest.mark.parametrize("epoch,iso", [
    ("1718444400", "2024-06-15T09:40:00"),
    ("0", "1970-01-01T00:00:00"),
    ("1", "1970-01-01T00:00:01"),
    ("1000000000", "2001-09-09T01:46:40"),
    ("1704067199", "2023-12-31T23:59:59"),
])
def test_epoch_keys_convert_to_utc(run, tmp_path, make_vault, epoch, iso):
    make_vault(make_v1_catalog(entries=[make_v1_entry(title={epoch: "A"})]))
    assert run("migrate", "vault").returncode == 0
    entry = read_catalog(tmp_path)["episodes"][0]
    assert list(entry["title"]) == [iso]


# Spec: "v1 UNIX-epoch conversion | ... in **UTC**" -- the conversion does not
# follow the machine's local timezone.
@pytest.mark.parametrize("tz", ["UTC", "America/New_York", "Asia/Tokyo"])
def test_epoch_conversion_ignores_local_timezone(tmp_path, make_vault, tz):
    make_vault(make_v1_catalog(entries=[make_v1_entry(title={EPOCH_A: "A"})]))
    env = dict(os.environ, TZ=tz)
    proc = subprocess.run([sys.executable, MVAULT, "migrate", "vault"],
                          cwd=str(tmp_path), capture_output=True, text=True,
                          env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    entry = read_catalog(tmp_path)["episodes"][0]
    assert list(entry["title"]) == [ISO_A]


# Spec: "| v1 category target | Every migrated entry goes to `episodes` |"
def test_every_v1_entry_goes_to_episodes(run, tmp_path, make_vault):
    ids = ["a", "b", "c", "d"]
    make_vault(make_v1_catalog(entries=[make_v1_entry(id=i) for i in ids]))
    run("migrate", "vault")
    catalog = read_catalog(tmp_path)
    assert sorted(e["id"] for e in catalog["episodes"]) == ids
    assert catalog["streams"] == [] and catalog["clips"] == []


# Spec: "| v1 `source_id` conversion |
# `https://media.example.com/channel/<source_id>` |"
def test_source_id_conversion_is_exact(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(source_id="xyz"))
    run("migrate", "vault")
    assert read_catalog(tmp_path)["source"] == \
        "https://media.example.com/channel/xyz"


# Spec: "| v3 reload | No additional history entry, ... |"
def test_v3_reload_adds_no_history_entry(run, tmp_path, make_vault):
    make_vault(make_v3_catalog(episodes=[make_v3_entry(id="e1")]))
    before = read_catalog(tmp_path)
    run("migrate", "vault")
    run("digest", "vault")
    after = read_catalog(tmp_path)
    assert after == before
    assert len(after["episodes"][0]["removed"]) == 1


# Spec: "v3 reload | ... no semantic modification, ..."
def test_v3_reload_makes_no_semantic_modification(run, tmp_path, make_vault):
    catalog = make_v3_catalog(episodes=[make_v3_entry(id="e1")],
                              streams=[make_v3_entry(id="s1")])
    make_vault(catalog)
    run("migrate", "vault")
    assert read_catalog(tmp_path) == catalog


# Spec: "v3 reload | ... no backup write |"
def test_v3_reload_writes_no_backup(run, tmp_path, make_vault):
    make_vault(make_v3_catalog(episodes=[make_v3_entry()]))
    run("migrate", "vault")
    run("digest", "vault")
    assert not os.path.exists(backup_path(tmp_path))


# Spec: "| Idempotence | Re-loading already migrated v3 catalog produces no
# further effects |"
def test_migration_is_idempotent(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=[make_v1_entry(id="a"),
                                        make_v1_entry(id="b")]))
    run("migrate", "vault")
    first = catalog_bytes(tmp_path)

    for _ in range(3):
        assert run("migrate", "vault").returncode == 0
        assert catalog_bytes(tmp_path) == first


# Spec: "Idempotence | Re-loading already migrated v3 catalog produces no
# further effects" -- a read-only load after migration changes nothing either.
def test_reload_after_migration_has_no_effect(run, tmp_path, make_vault):
    make_vault(make_v2_catalog())
    run("migrate", "vault")
    migrated = catalog_bytes(tmp_path)
    assert run("digest", "vault").returncode == 0
    assert catalog_bytes(tmp_path) == migrated


# Spec: "Migration-added timestamp scope | Each migration-added `removed`
# timestamp must be ISO 8601" + "v1 UNIX-epoch conversion" -- the migrated
# history is consistent, i.e. the migration stamp is not older than the
# converted keys it sits beside (see AMBIGUITIES T18).
def test_migration_timestamp_is_the_newest_key(run, tmp_path, make_vault):
    make_vault(make_v1_catalog(entries=[make_v1_entry(
        title={EPOCH_A: "old", EPOCH_B: "new"})]))
    run("migrate", "vault")
    entry = read_catalog(tmp_path)["episodes"][0]
    (stamp,) = list(entry["removed"])
    assert stamp > ISO_B
