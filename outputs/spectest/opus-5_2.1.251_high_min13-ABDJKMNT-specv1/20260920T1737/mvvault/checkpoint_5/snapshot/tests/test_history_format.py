"""Spec section: `tracked field` History Format / determinism of sync timestamps."""

import json

from conftest import current, find_entry, history_order, read_catalog, source_entry


def sync(run_cli):
    result = run_cli("sync", "demo")
    assert result.returncode == 0, result.stderr


def all_keys(catalog):
    return [
        key
        for category in ("episodes", "streams", "clips")
        for entry in catalog[category]
        for field in ("title", "description", "views", "likes", "preview", "removed")
        for key in entry[field]
    ]


# Phrase: "Value selection | Current value = value at latest datetime key"
def test_current_value_comes_from_latest_key_not_insertion_order(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", title="old")])
    sync(run_cli)

    catalog = read_catalog(vault)
    entry = find_entry(catalog, "episodes", "e1")
    first_key = next(iter(entry["title"]))
    entry["title"] = {"2030-01-01T00:00:00": "latest", first_key: "old"}
    (vault / "catalog.json").write_text(json.dumps(catalog))

    # "latest" is already the current value, so re-serving it must not append.
    source.serve(episodes=[source_entry("e1", title="latest")])
    sync(run_cli)
    assert len(find_entry(read_catalog(vault), "episodes", "e1")["title"]) == 2


# Phrase: "Comparison order | Chronological timestamp order"
def test_changed_value_compares_against_chronologically_latest(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", views=1)])
    sync(run_cli)

    catalog = read_catalog(vault)
    entry = find_entry(catalog, "episodes", "e1")
    first_key = next(iter(entry["views"]))
    entry["views"] = {"2030-01-01T00:00:00": 99, first_key: 1}
    (vault / "catalog.json").write_text(json.dumps(catalog))

    source.serve(episodes=[source_entry("e1", views=1)])
    sync(run_cli)
    views = find_entry(read_catalog(vault), "episodes", "e1")["views"]
    assert len(views) == 3
    assert current(views) == 1


# Phrase: "Collision handling | When a new history entry would reuse an existing or
# non-newer second, advance to a strictly later second before writing"
def test_new_entry_advances_past_existing_timestamp(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1", title="old")])
    sync(run_cli)

    catalog = read_catalog(vault)
    entry = find_entry(catalog, "episodes", "e1")
    entry["title"] = {"2030-01-01T00:00:00": "old"}
    (vault / "catalog.json").write_text(json.dumps(catalog))

    source.serve(episodes=[source_entry("e1", title="new")])
    sync(run_cli)

    title = find_entry(read_catalog(vault), "episodes", "e1")["title"]
    keys = history_order(title)
    assert keys[-1] > "2030-01-01T00:00:00"
    assert title[keys[-1]] == "new"


# Phrase: "Sync timestamps | ... remain strictly increasing whenever new history entries are appended"
def test_rapid_syncs_produce_strictly_increasing_timestamps(run_cli, source, vault):
    for views in (1, 2, 3, 4):
        source.serve(episodes=[source_entry("e1", views=views)])
        sync(run_cli)

    views = find_entry(read_catalog(vault), "episodes", "e1")["views"]
    keys = history_order(views)
    assert len(keys) == 4
    assert keys == sorted(set(keys))
    assert [views[key] for key in keys] == [1, 2, 3, 4]


# Phrase: "Collision handling" - the advance applies across entries within one catalog
def test_appends_never_reuse_an_existing_second(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1"), source_entry("e2")])
    sync(run_cli)
    source.serve(episodes=[source_entry("e1", views=2), source_entry("e2", views=3)])
    sync(run_cli)

    catalog = read_catalog(vault)
    per_field_keys = [
        tuple(history_order(find_entry(catalog, "episodes", entry_id)["views"]))
        for entry_id in ("e1", "e2")
    ]
    for keys in per_field_keys:
        assert len(set(keys)) == len(keys)
    assert per_field_keys[0][-1] > per_field_keys[0][0]


# Phrase: "Sync timestamps | Reflect sync execution time"
def test_sync_timestamps_track_wall_clock(run_cli, source, vault):
    import datetime

    before = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(seconds=2)
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)
    after = datetime.datetime.now().replace(microsecond=0) + datetime.timedelta(seconds=2)

    stamp = all_keys(read_catalog(vault))[0]
    assert before.strftime("%Y-%m-%dT%H:%M:%S") <= stamp <= after.strftime("%Y-%m-%dT%H:%M:%S")


# Phrase: "JSON object key order | Not part of the contract"
def test_history_is_a_json_object(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    sync(run_cli)
    raw = json.loads((vault / "catalog.json").read_text())
    assert isinstance(raw["episodes"][0]["title"], dict)
