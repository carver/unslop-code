"""Spec sections: `tracked field` History Format (collisions), `mvault` Determinism."""

import json
import re
from datetime import datetime

import pytest

from conftest import TIMESTAMP_RE, latest, payload, read_catalog, source_entry, timestamps

TRACKED_FIELDS = ["title", "description", "views", "likes", "preview", "removed"]


def rewrite_catalog(vault, mutate):
    catalog = read_catalog(vault)
    mutate(catalog)
    (vault / "catalog.json").write_text(json.dumps(catalog))


# Spec: Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix
def test_sync_timestamps_have_no_timezone_suffix(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    for key in read_catalog(vault)["episodes"][0]["title"]:
        assert TIMESTAMP_RE.match(key), key


# Spec: Datetime text | `YYYY-MM-DDTHH:MM:SS` (parseable, second resolution)
def test_sync_timestamps_parse_as_naive_datetimes(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    key = next(iter(read_catalog(vault)["episodes"][0]["views"]))
    parsed = datetime.fromisoformat(key)
    assert parsed.tzinfo is None
    assert parsed.microsecond == 0


# Spec: Sync timestamps | Reflect sync execution time
def test_sync_timestamp_is_close_to_execution_time(run, source, vault):
    before = datetime.now().replace(microsecond=0)
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    after = datetime.now().replace(microsecond=0)

    key = datetime.fromisoformat(next(iter(read_catalog(vault)["episodes"][0]["views"])))
    assert before <= key <= after


# Spec: Date-only source values | Normalize to `00:00:00` time component
def test_date_only_published_normalizes(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", published="2024-03-05")]))
    run("sync", "vault")
    assert read_catalog(vault)["episodes"][0]["published"] == "2024-03-05T00:00:00"


# Spec: Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix (stored `published`)
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-03-05T06:07:08", "2024-03-05T06:07:08"),
        ("2024-03-05T06:07:08.123456", "2024-03-05T06:07:08"),
        ("2024-03-05T06:07:08Z", "2024-03-05T06:07:08"),
        ("2024-03-05T06:07:08+05:00", "2024-03-05T06:07:08"),
        ("2024-03-05 06:07:08", "2024-03-05T06:07:08"),
    ],
)
def test_published_is_normalized_to_plain_datetime_text(run, source, vault, raw, expected):
    source.serve(payload(episodes=[source_entry("e1", published=raw)]))
    assert run("sync", "vault").returncode == 0
    assert read_catalog(vault)["episodes"][0]["published"] == expected


# Spec: Collision handling | When a new history entry would reuse an existing or
# non-newer second, advance to a strictly later second before writing
def test_new_entry_advances_past_a_future_timestamp(run, source, vault):
    future = "2099-01-01T00:00:00"
    source.serve(payload(episodes=[source_entry("e1", views=1)]))
    run("sync", "vault")
    rewrite_catalog(vault, lambda c: c["episodes"][0]["views"].update({future: 1}))

    source.serve(payload(episodes=[source_entry("e1", views=2)]))
    run("sync", "vault")

    history = read_catalog(vault)["episodes"][0]["views"]
    assert max(history) > future
    assert history[max(history)] == 2


# Spec: Collision handling | ... would reuse an existing ... second
def test_history_key_is_never_overwritten(run, source, vault):
    now = datetime.now().replace(microsecond=0).isoformat()
    source.serve(payload(episodes=[source_entry("e1", title="a")]))
    run("sync", "vault")
    rewrite_catalog(vault, lambda c: c["episodes"][0]["title"].update({now: "a"}))
    before = len(read_catalog(vault)["episodes"][0]["title"])

    source.serve(payload(episodes=[source_entry("e1", title="b")]))
    run("sync", "vault")

    history = read_catalog(vault)["episodes"][0]["title"]
    assert len(history) == before + 1
    assert history[now] == "a"


# Spec: Sync timestamps ... remain strictly increasing whenever new history
# entries are appended
def test_rapid_syncs_produce_strictly_increasing_timestamps(run, source, vault):
    for views in range(5):
        source.serve(payload(episodes=[source_entry("e1", views=views)]))
        run("sync", "vault")

    keys = timestamps(read_catalog(vault)["episodes"][0]["views"])
    assert len(keys) == 5
    assert keys == sorted(set(keys))


# Spec: Sync timestamps ... strictly increasing (across fields of one entry, T1)
def test_later_sync_timestamps_exceed_all_earlier_ones(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", title="a", views=1)]))
    run("sync", "vault")
    first = max(read_catalog(vault)["episodes"][0]["title"])

    source.serve(payload(episodes=[source_entry("e1", title="b", views=2)]))
    run("sync", "vault")

    entry = read_catalog(vault)["episodes"][0]
    assert max(entry["title"]) > first
    assert max(entry["title"]) == max(entry["views"])


# Spec: Sync timestamps ... strictly increasing (one timestamp per sync run, T1)
def test_all_appends_in_one_sync_share_a_timestamp(run, source, vault):
    source.serve(payload(episodes=[source_entry("a"), source_entry("b")]))
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("a", views=50), source_entry("b", title="new")]))
    run("sync", "vault")

    catalog = read_catalog(vault)
    stamps = {max(e["views"]) for e in catalog["episodes"]} | {
        max(e["title"]) for e in catalog["episodes"]
    }
    assert len(stamps) == 2  # the initial sync timestamp and the second one


# Spec: History interpretation | Chronological timestamp order
def test_out_of_order_keys_are_read_chronologically(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", views=10)]))
    run("sync", "vault")
    rewrite_catalog(
        vault,
        lambda c: c["episodes"][0]["views"].update({"2000-01-01T00:00:00": 999}),
    )

    source.serve(payload(episodes=[source_entry("e1", views=10)]))
    run("sync", "vault")

    history = read_catalog(vault)["episodes"][0]["views"]
    assert latest(history) == 10
    assert len(history) == 2  # 10 is still current, so nothing was appended


# Spec: Locale | No locale-sensitive formatting anywhere
def test_output_is_ascii_and_locale_independent(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1", published="2024-12-31")]))
    run("sync", "vault")
    text = (vault / "catalog.json").read_text()
    assert not re.search(r"\d{2}/\d{2}/\d{4}", text)
    assert "2024-12-31T00:00:00" in text


# Spec: Datetime text | `YYYY-MM-DDTHH:MM:SS` (every key in every history)
def test_all_history_keys_share_one_format(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")], streams=[source_entry("s1")]))
    run("sync", "vault")
    source.serve(payload(episodes=[source_entry("e1", views=3)]))
    run("sync", "vault")

    catalog = read_catalog(vault)
    for category in ("episodes", "streams", "clips"):
        for entry in catalog[category]:
            for field in TRACKED_FIELDS:
                for key in entry[field]:
                    assert TIMESTAMP_RE.match(key), key
