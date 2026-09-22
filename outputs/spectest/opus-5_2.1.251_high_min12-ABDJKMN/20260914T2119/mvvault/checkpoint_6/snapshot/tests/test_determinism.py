"""Spec: `mvault` Determinism and the remaining Error Handling rows."""
import json
import os
import re
from datetime import datetime, timedelta

import pytest

from conftest import (TRACKED_FIELDS, TS_RE, all_keys, current, find_entry,
                      make_entry, parse_ts, read_catalog, sorted_keys)


# Spec: "| Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |" --
# history keys.
def test_history_keys_have_no_timezone_suffix(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    keys = all_keys(catalog)
    assert keys
    for key in keys:
        assert TS_RE.match(key), key
        assert not key.endswith("Z")
        assert "+" not in key


# Spec: "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix" --
# stored `published`.
@pytest.mark.parametrize("given,expected", [
    ("2024-05-01T12:00:00", "2024-05-01T12:00:00"),
    ("2024-05-01T12:00:00Z", "2024-05-01T12:00:00"),
    ("2024-12-31T23:59:59", "2024-12-31T23:59:59"),
])
def test_published_rendered_without_timezone_suffix(run, source, tmp_path, vault,
                                                    given, expected):
    source.serve(episodes=[make_entry(id="e1", published=given)])
    assert run("sync", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert entry["published"] == expected


# Spec: "| Date-only source values | Normalize to `00:00:00` time component |"
@pytest.mark.parametrize("given,expected", [
    ("2024-05-01", "2024-05-01T00:00:00"),
    ("1999-12-31", "1999-12-31T00:00:00"),
])
def test_date_only_published_normalized(run, source, tmp_path, vault, given, expected):
    source.serve(episodes=[make_entry(id="e1", published=given)])
    assert run("sync", "vault").returncode == 0
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert entry["published"] == expected


# Spec: "Date-only source values | Normalize to `00:00:00`" -- normalization is
# stable, so a re-sync of the same date is not seen as a change.
def test_date_only_normalization_is_stable(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", published="2024-05-01")])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="e1", published="2024-05-01")])
    run("sync", "vault")
    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    assert entry["published"] == "2024-05-01T00:00:00"
    for field in TRACKED_FIELDS:
        assert len(entry[field]) == 1, field


# Spec: "| Sync timestamps | Reflect sync execution time ... |"
def test_sync_timestamp_reflects_execution_time(run, source, tmp_path, vault):
    before = datetime.now().replace(microsecond=0) - timedelta(seconds=2)
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault")
    after = datetime.now().replace(microsecond=0) + timedelta(seconds=2)

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    stamp = parse_ts(next(iter(entry["title"])))
    assert before <= stamp <= after


# Spec: "| Sync timestamps | ... remain strictly increasing whenever new history
# entries are appended |"
def test_sync_timestamps_strictly_increasing(run, source, tmp_path, vault):
    stamps = []
    for i in range(4):
        source.serve(episodes=[make_entry(id="e1", views=i)])
        assert run("sync", "vault").returncode == 0
        entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
        stamps.append(sorted_keys(entry["views"])[-1])

    assert len(entry["views"]) == 4
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == 4


# Spec: "Sync timestamps ... strictly increasing" -- across entries too: a new
# entry added by a later sync must not carry an earlier stamp than an entry
# already in the catalog (see AMBIGUITIES T2).
def test_later_sync_stamps_newer_than_existing_history(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="first")])
    run("sync", "vault")
    first_keys = all_keys(read_catalog(tmp_path))

    source.serve(episodes=[make_entry(id="first"), make_entry(id="second")])
    run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "second")
    new_stamp = next(iter(entry["title"]))
    assert new_stamp > max(first_keys)


# Spec: "Sync timestamps ... strictly increasing whenever new history entries
# are appended" -- syncs that append nothing need not advance anything.
def test_no_op_sync_does_not_append_timestamps(run, source, tmp_path, vault):
    payload = [make_entry(id="e1")]
    source.serve(episodes=payload)
    run("sync", "vault")
    before = sorted(all_keys(read_catalog(tmp_path)))
    source.serve(episodes=payload)
    run("sync", "vault")
    assert sorted(all_keys(read_catalog(tmp_path))) == before


# Spec: "| History interpretation | Chronological timestamp order |" -- values
# are read back in timestamp order regardless of how many syncs wrote them.
def test_history_reads_chronologically(run, source, tmp_path, vault):
    values = ["v0", "v1", "v2", "v3"]
    for value in values:
        source.serve(episodes=[make_entry(id="e1", title=value)])
        run("sync", "vault")

    entry = find_entry(read_catalog(tmp_path), "episodes", "e1")
    keys = sorted_keys(entry["title"])
    assert [entry["title"][k] for k in keys] == values
    assert current(entry["title"]) == "v3"


# Spec: "| Locale | No locale-sensitive formatting anywhere |" -- output is
# identical under a non-C locale.
def test_output_is_locale_independent(run, source, tmp_path):
    import subprocess
    import sys
    from conftest import MVAULT

    source_url = source.url
    source.serve(episodes=[make_entry(id="e1", published="2024-05-01",
                                      views=1234567, likes=None)])

    def sync_under(env_overrides, name):
        env = dict(os.environ)
        env.update(env_overrides)
        subprocess.run([sys.executable, MVAULT, "init", name, source_url],
                       cwd=str(tmp_path), capture_output=True, text=True,
                       timeout=60, env=env)
        proc = subprocess.run([sys.executable, MVAULT, "sync", name],
                              cwd=str(tmp_path), capture_output=True, text=True,
                              timeout=60, env=env)
        assert proc.returncode == 0, proc.stderr
        return read_catalog(tmp_path, name)

    a = sync_under({"LC_ALL": "C", "LANG": "C"}, "va")
    b = sync_under({"LC_ALL": "de_DE.UTF-8", "LANG": "de_DE.UTF-8"}, "vb")

    def strip(catalog):
        for entry in catalog["episodes"]:
            for field in TRACKED_FIELDS:
                entry[field] = sorted(entry[field].values(), key=repr)
        catalog["source"] = ""
        return catalog

    assert strip(a) == strip(b)
    assert a["episodes"][0]["published"] == "2024-05-01T00:00:00"


# Spec: "Locale | No locale-sensitive formatting anywhere" -- digits are ASCII
# and numbers carry no grouping separators.
def test_numbers_are_plain_ascii(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", views=1234567, width=3840,
                                      height=2160)])
    run("sync", "vault")
    text = (tmp_path / "vault" / "catalog.json").read_text(encoding="utf-8")
    assert "1234567" in text
    assert "1,234,567" not in text
    assert "1.234.567" not in text


# Spec: "| Entry order | Newest `published` first; ties break by
# lexicographically smaller `id` |" -- restated in the Determinism table; the
# byte content of two identical vaults must agree apart from timestamps.
def test_entry_order_is_deterministic_across_runs(run, source, tmp_path):
    entries = [make_entry(id=i, published="2024-01-0%d" % (n + 1))
               for n, i in enumerate(["c", "a", "b"])]
    orders = []
    for name in ("v1", "v2"):
        run("init", name, source.url)
        source.serve(episodes=entries)
        assert run("sync", name).returncode == 0
        orders.append([e["id"] for e in read_catalog(tmp_path, name)["episodes"]])
    assert orders[0] == orders[1] == ["b", "a", "c"]


# Spec: Error Handling -- "Source metadata fetch failure | stderr | non-zero |
# Error message; malformed source entries are included in this case".
def test_fetch_failure_message_on_stderr(run, source, tmp_path, vault):
    bad = make_entry(id="x")
    bad["views"] = "lots"
    source.serve(episodes=[bad])
    res = run("sync", "vault")
    assert res.returncode != 0
    assert res.stderr.strip() != ""
    assert res.stdout == ""


# Spec: Error Handling rows all require a non-zero exit with output on stderr
# and nothing on stdout.
@pytest.mark.parametrize("argv", [
    (),                                   # no subcommand
    ("sync", "nope"),                     # non-existent vault
    ("bogus",),                           # unknown subcommand
])
def test_error_rows_use_stderr_and_non_zero_exit(run, argv):
    res = run(*argv)
    assert res.returncode != 0
    assert res.stderr != ""
    assert res.stdout == ""
