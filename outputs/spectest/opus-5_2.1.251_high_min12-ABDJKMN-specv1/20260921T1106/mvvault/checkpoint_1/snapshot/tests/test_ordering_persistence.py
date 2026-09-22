"""Spec sections: `catalog.json` Ordering / Persistence / `mvault` Determinism."""
import json
import re

import pytest
from conftest import entry, find, latest, payload, read_bytes, read_catalog

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def sync_with(run, source, entries, name="v", category="episodes"):
    source.payload = payload(**{category: entries})
    result = run("sync", name)
    assert result.returncode == 0, result.stderr
    return result


# Phrase: "Sort Key Priority 1 | Newest `published` first"
def test_entries_sorted_newest_published_first(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [
        entry("old", published="2021-01-01T00:00:00"),
        entry("new", published="2024-12-31T23:59:59"),
        entry("mid", published="2023-06-15T12:00:00"),
    ])
    catalog = read_catalog(tmp_path / "v")
    assert [e["id"] for e in catalog["episodes"]] == ["new", "mid", "old"]


# Phrase: "Sort Key Priority 2 | Lexicographically smaller `id` first when
#          `published` values are equal"
def test_ties_break_by_lexicographically_smaller_id(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [
        entry("b2", published="2024-01-01T00:00:00"),
        entry("a10", published="2024-01-01T00:00:00"),
        entry("a2", published="2024-01-01T00:00:00"),
        entry("B1", published="2024-01-01T00:00:00"),
    ])
    catalog = read_catalog(tmp_path / "v")
    assert [e["id"] for e in catalog["episodes"]] == ["B1", "a10", "a2", "b2"]


# Phrase: "Entry order | Newest `published` first; ties break by
#          lexicographically smaller `id`"
# Context: ordering is maintained as entries are added by later syncs, and
# holds in every category.
def test_order_maintained_across_syncs_and_categories(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    source.payload = payload(
        episodes=[entry("e-old", published="2020-01-01T00:00:00")],
        clips=[entry("c-old", published="2020-01-01T00:00:00")],
    )
    assert run("sync", "v").returncode == 0
    source.payload = payload(
        episodes=[entry("e-old", published="2020-01-01T00:00:00"),
                  entry("e-new", published="2025-01-01T00:00:00")],
        clips=[entry("c-old", published="2020-01-01T00:00:00"),
               entry("c-new", published="2025-01-01T00:00:00")],
    )
    assert run("sync", "v").returncode == 0
    catalog = read_catalog(tmp_path / "v")
    assert [e["id"] for e in catalog["episodes"]] == ["e-new", "e-old"]
    assert [e["id"] for e in catalog["clips"]] == ["c-new", "c-old"]


# Phrase: "Entry order" — removed entries stay in order, not moved or dropped.
def test_removed_entries_keep_their_place_in_order(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [
        entry("a", published="2024-01-01T00:00:00"),
        entry("b", published="2023-01-01T00:00:00"),
        entry("c", published="2022-01-01T00:00:00"),
    ])
    sync_with(run, source, [entry("c", published="2022-01-01T00:00:00")])
    catalog = read_catalog(tmp_path / "v")
    assert [e["id"] for e in catalog["episodes"]] == ["a", "b", "c"]


# Phrase: "Date-only source values | Normalize to `00:00:00` time component"
def test_date_only_published_normalized(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1", published="2024-03-04")])
    assert read_catalog(tmp_path / "v")["episodes"][0]["published"] == "2024-03-04T00:00:00"


# Phrase: "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix"
# Context: stored `published` carries no timezone suffix. See AMBIGUITIES.md T6.
@pytest.mark.parametrize(
    "given,expected",
    [
        ("2024-03-04T05:06:07", "2024-03-04T05:06:07"),
        ("2024-03-04T05:06:07Z", "2024-03-04T05:06:07"),
        ("2024-03-04T05:06:07.123456", "2024-03-04T05:06:07"),
        ("2024-03-04 05:06:07", "2024-03-04T05:06:07"),
        ("2024-03-04", "2024-03-04T00:00:00"),
    ],
)
def test_published_normalized_to_bare_datetime_text(run, source, tmp_path, given, expected):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1", published=given)])
    assert read_catalog(tmp_path / "v")["episodes"][0]["published"] == expected


# Phrase: "Normalize to `00:00:00`" — normalized values participate in ordering.
def test_normalized_published_used_for_ordering(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [
        entry("dateonly", published="2024-03-04"),
        entry("sameday", published="2024-03-04T00:00:01"),
    ])
    assert [e["id"] for e in read_catalog(tmp_path / "v")["episodes"]] == ["sameday", "dateonly"]


# Phrase: "Backup trigger | Before every write to existing `catalog.json`" +
#         "Backup path | `catalog.bak`"
def test_backup_written_next_to_catalog(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1")])
    assert (tmp_path / "v" / "catalog.bak").is_file()


# Phrase: "Backup content | Byte-for-byte copy of pre-write `catalog.json`"
def test_backup_is_byte_for_byte_pre_write_copy(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    before = read_bytes(tmp_path / "v" / "catalog.json")
    sync_with(run, source, [entry("e1")])
    assert read_bytes(tmp_path / "v" / "catalog.bak") == before
    assert read_bytes(tmp_path / "v" / "catalog.json") != before


# Phrase: "Backup overwrite | Replace existing `catalog.bak`"
def test_backup_replaced_on_each_write(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1", title="A")])
    first_catalog = read_bytes(tmp_path / "v" / "catalog.json")
    sync_with(run, source, [entry("e1", title="B")])
    assert read_bytes(tmp_path / "v" / "catalog.bak") == first_catalog


# Phrase: "Backup content | Byte-for-byte copy of pre-write `catalog.json`"
# Context: the backup always holds valid, loadable catalog content.
def test_backup_is_loadable_previous_catalog(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1", views=1)])
    sync_with(run, source, [entry("e1", views=2)])
    backup = json.loads((tmp_path / "v" / "catalog.bak").read_text(encoding="utf-8"))
    assert latest(find(backup, "episodes", "e1")["views"]) == 1
    assert latest(find(read_catalog(tmp_path / "v"), "episodes", "e1")["views"]) == 2


# Phrase: "Sync timestamps | Reflect sync execution time"
def test_sync_timestamp_reflects_execution_time(run, source, tmp_path):
    import datetime as _dt

    assert run("init", "v", source.url).returncode == 0
    before = _dt.datetime.now().replace(microsecond=0) - _dt.timedelta(seconds=5)
    sync_with(run, source, [entry("e1")])
    after = _dt.datetime.now().replace(microsecond=0) + _dt.timedelta(seconds=5)
    stamp = list(read_catalog(tmp_path / "v")["episodes"][0]["title"])[0]
    parsed = _dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S")
    assert before <= parsed <= after


# Phrase: "Collision handling | When a new history entry would reuse an
#          existing or non-newer second, advance to a strictly later second
#          before writing"
# Context: back-to-back syncs within the same wall-clock second.
def test_rapid_syncs_get_strictly_later_timestamps(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    for views in range(5):
        sync_with(run, source, [entry("e1", views=views)])
    history = read_catalog(tmp_path / "v")["episodes"][0]["views"]
    keys = list(history)
    assert len(keys) == 5
    assert keys == sorted(set(keys))
    assert [history[k] for k in sorted(history)] == [0, 1, 2, 3, 4]


# Phrase: "Sync timestamps | ... remain strictly increasing whenever new
#          history entries are appended"
# Context: a catalog whose newest history key is in the future still advances.
# See AMBIGUITIES.md T2.
def test_future_history_key_forces_strictly_later_timestamp(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1", views=1)])
    catalog = read_catalog(tmp_path / "v")
    stored = catalog["episodes"][0]
    for field in ("title", "description", "views", "likes", "preview", "removed"):
        value = list(stored[field].values())[0]
        stored[field] = {"2099-01-01T00:00:00": value}
    (tmp_path / "v" / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    sync_with(run, source, [entry("e1", views=2)])

    history = read_catalog(tmp_path / "v")["episodes"][0]["views"]
    assert len(history) == 2
    new_key = max(history)
    assert new_key > "2099-01-01T00:00:00"
    assert TS_RE.match(new_key)
    assert history[new_key] == 2


# Phrase: "Sync timestamps ... strictly increasing" — all new history entries
# written by one sync share that single timestamp.
def test_all_appends_in_one_sync_share_one_timestamp(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("a", title="A"), entry("b", title="B")])
    sync_with(run, source, [entry("a", title="A2"), entry("c", title="C")])
    catalog = read_catalog(tmp_path / "v")
    a = find(catalog, "episodes", "a")
    b = find(catalog, "episodes", "b")
    c = find(catalog, "episodes", "c")
    second = max(a["title"])
    assert second == max(b["removed"])            # b's removal
    assert second == max(c["title"])              # c's first observation


# Phrase: "JSON object key order | Not part of the contract"
# Context: history is read by key value, so any stored order is acceptable,
# but keys must remain unique and parseable.
def test_history_keys_unique_and_parseable(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    for views in (1, 2, 3):
        sync_with(run, source, [entry("e1", views=views)])
    raw = (tmp_path / "v" / "catalog.json").read_text(encoding="utf-8")
    history = json.loads(raw)["episodes"][0]["views"]
    assert len(history) == 3
    for key in history:
        assert TS_RE.match(key)


# Phrase: "Locale | No locale-sensitive formatting anywhere"
# Context: run the CLI under a non-C locale; output text is unchanged.
def test_output_is_locale_independent(run, source, tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from conftest import MVAULT

    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1", published="2024-03-04")])
    expected = read_bytes(tmp_path / "v" / "catalog.json")

    env = dict(os.environ, LC_ALL="de_DE.UTF-8", LANG="de_DE.UTF-8",
               LC_TIME="de_DE.UTF-8", TZ="Europe/Berlin")
    assert run("init", "w", source.url).returncode == 0
    result = subprocess.run([sys.executable, MVAULT, "sync", "w"],
                            cwd=str(tmp_path), capture_output=True, text=True,
                            env=env, timeout=60)
    assert result.returncode == 0, result.stderr
    got = read_catalog(tmp_path / "w")["episodes"][0]
    assert got["published"] == "2024-03-04T00:00:00"
    assert json.loads(expected)["episodes"][0]["published"] == got["published"]
    assert TS_RE.match(max(got["title"]))


# Phrase: "`catalog.json` Root Schema" — sync preserves the root fields.
def test_sync_preserves_root_schema(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1")])
    catalog = read_catalog(tmp_path / "v")
    assert catalog["version"] == 3
    assert catalog["source"] == source.url
    assert set(catalog) == {"version", "source", "episodes", "streams", "clips"}


# Phrase: "Static | `published` | Original publication datetime"
# Context: static fields keep their first-observed values. See AMBIGUITIES.md T7.
def test_static_fields_stay_at_first_observation(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1", published="2024-01-01T00:00:00",
                                  width=1920, height=1080)])
    sync_with(run, source, [entry("e1", published="2025-09-09T09:09:09",
                                  width=640, height=480)])
    stored = read_catalog(tmp_path / "v")["episodes"][0]
    assert stored["published"] == "2024-01-01T00:00:00"
    assert stored["width"] == 1920
    assert stored["height"] == 1080


# Phrase: "Backup trigger | Before every write to existing `catalog.json`"
# Context: a sync that changes nothing still rewrites the catalog, so the
# backup tracks it. See AMBIGUITIES.md T8.
def test_no_change_sync_still_succeeds_and_keeps_catalog_valid(run, source, tmp_path):
    assert run("init", "v", source.url).returncode == 0
    sync_with(run, source, [entry("e1")])
    snapshot = read_catalog(tmp_path / "v")
    result = run("sync", "v")
    assert result.returncode == 0, result.stderr
    assert read_catalog(tmp_path / "v") == snapshot
