"""Spec section: `sync` Update Rules."""

from __future__ import annotations

TRACKED = ("title", "description", "views", "likes", "preview", "removed")


# Spec: | First observation | Add entry to matching category; ... |
def test_first_observation_adds_entry_to_matching_category(
    run_cli, vault, source, helpers, workdir
):
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("e1")],
        streams=[helpers.make_source_entry("s1")],
        clips=[helpers.make_source_entry("c1")],
    ))
    assert run_cli("sync", "vault").returncode == 0
    catalog = helpers.read_catalog(workdir)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]
    assert [e["id"] for e in catalog["streams"]] == ["s1"]
    assert [e["id"] for e in catalog["clips"]] == ["c1"]


# Spec: | First observation | ... create initial history entry for all six tracked fields ... |
def test_first_observation_creates_one_history_entry_per_tracked_field(
    run_cli, vault, source, helpers, workdir
):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in TRACKED:
        assert len(entry[field]) == 1, (field, entry[field])


# Spec: | First observation | ... set `removed` to `false` at sync timestamp |
def test_first_observation_sets_removed_false(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(entry["removed"]) is False


# Spec: | First observation | ... at sync timestamp | (one shared timestamp per sync run)
# See AMBIGUITIES.md T4.
def test_first_observation_uses_one_sync_timestamp_for_all_fields(
    run_cli, vault, source, helpers, workdir
):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    stamps = {helpers.latest_key(entry[field]) for field in TRACKED}
    assert len(stamps) == 1


# Spec: | Existing entry, unchanged tracked value | No new history entry for that field |
def test_unchanged_values_add_no_history(run_cli, vault, source, helpers, workdir):
    payload = helpers.make_payload(episodes=[helpers.make_source_entry("e1")])
    source.set(payload)
    assert run_cli("sync", "vault").returncode == 0
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in TRACKED:
        assert len(entry[field]) == 1, (field, entry[field])


# Spec: | Existing entry, changed tracked value | Append new history entry at sync timestamp |
def test_changed_title_appends_history(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="old")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="new")]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert len(entry["title"]) == 2
    assert helpers.current(entry["title"]) == "new"


# Spec: | Existing entry, changed tracked value | ... (only the changed field grows)
def test_only_changed_field_gains_history(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=5)]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=6)]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert len(entry["views"]) == 2
    for field in ("title", "description", "likes", "preview", "removed"):
        assert len(entry[field]) == 1, field


# Spec: | Existing entry, changed tracked value | ... (every tracked field can change)
def test_each_tracked_source_field_is_tracked_for_changes(
    run_cli, vault, source, helpers, workdir
):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry(
        "e1", title="T2", description="D2", views=999, likes=42, preview="P2")]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field, value in (("title", "T2"), ("description", "D2"),
                         ("views", 999), ("likes", 42), ("preview", "P2")):
        assert len(entry[field]) == 2, field
        assert helpers.current(entry[field]) == value


# Spec: | Existing entry ... | (static fields are not re-versioned and stay put)
def test_static_fields_remain_scalars_across_syncs(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="a")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="b")]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["width"] == 1920
    assert entry["height"] == 1080
    assert entry["published"] == "2024-05-01T08:30:00"


# Spec: | Entry absent from current source | Append `removed: true` at sync timestamp |
def test_absent_entry_marked_removed(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(entry["removed"]) is True
    keys = helpers.keys_sorted(entry["removed"])
    assert [entry["removed"][k] for k in keys] == [False, True]


# Spec: | Removal handling | Never delete entry from `catalog.json` |
def test_removed_entry_is_retained_with_history(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="kept")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload())
    assert run_cli("sync", "vault").returncode == 0

    catalog = helpers.read_catalog(workdir)
    assert len(catalog["episodes"]) == 1
    entry = catalog["episodes"][0]
    assert helpers.current(entry["title"]) == "kept"


# Spec: | Entry absent from current source | ... (still absent -> unchanged -> no new entry)
def test_repeated_absence_does_not_append_again(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload())
    assert run_cli("sync", "vault").returncode == 0
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert len(entry["removed"]) == 2


# Spec: | Entry absent from current source | ... (other tracked fields do not change)
def test_absence_does_not_touch_other_tracked_fields(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload())
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in ("title", "description", "views", "likes", "preview"):
        assert len(entry[field]) == 1, field


# Spec: | Previously removed entry reappears | Append `removed: false` at sync timestamp |
def test_reappearing_entry_marked_not_removed(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload())
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    keys = helpers.keys_sorted(entry["removed"])
    assert [entry["removed"][k] for k in keys] == [False, True, False]


# Spec: | Previously removed entry reappears | ... (changes during the absence are recorded too)
def test_reappearing_entry_records_changed_fields(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=1)]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload())
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=50)]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert helpers.current(entry["views"]) == 50
    assert len(entry["views"]) == 2
    assert helpers.current(entry["removed"]) is False


# Spec: | Previously removed entry reappears | ... (reappearing unchanged adds only `removed`)
def test_reappearing_unchanged_entry_only_appends_removed(
    run_cli, vault, source, helpers, workdir
):
    entry_payload = helpers.make_source_entry("e1")
    source.set(helpers.make_payload(episodes=[entry_payload]))
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload())
    assert run_cli("sync", "vault").returncode == 0
    source.set(helpers.make_payload(episodes=[entry_payload]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert len(entry["removed"]) == 3
    for field in ("title", "description", "views", "likes", "preview"):
        assert len(entry[field]) == 1, field


# Spec: | Success effect | Update catalog with new, changed, removed, and restored entries |
# Context: all four cases in a single sync run.
def test_single_sync_handles_new_changed_removed_and_restored(
    run_cli, vault, source, helpers, workdir
):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("keep", views=1),
        helpers.make_source_entry("gone"),
        helpers.make_source_entry("back"),
    ]))
    assert run_cli("sync", "vault").returncode == 0

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("keep", views=1)]))
    assert run_cli("sync", "vault").returncode == 0  # gone + back removed

    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("keep", views=2),   # changed
        helpers.make_source_entry("back"),            # restored
        helpers.make_source_entry("fresh"),           # new
    ]))
    assert run_cli("sync", "vault").returncode == 0

    catalog = helpers.read_catalog(workdir)
    ids = {e["id"] for e in catalog["episodes"]}
    assert ids == {"keep", "gone", "back", "fresh"}
    assert helpers.current(helpers.find_entry(catalog, "keep")["views"]) == 2
    assert helpers.current(helpers.find_entry(catalog, "gone")["removed"]) is True
    assert helpers.current(helpers.find_entry(catalog, "back")["removed"]) is False
    assert helpers.current(helpers.find_entry(catalog, "fresh")["removed"]) is False


# Spec: | First observation | Add entry to matching category |
# Context: per-category reconciliation; see AMBIGUITIES.md T7.
def test_categories_are_reconciled_independently(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("x")],
        streams=[helpers.make_source_entry("y")],
    ))
    assert run_cli("sync", "vault").returncode == 0
    # drop the stream only; the episode must stay present
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("x")]))
    assert run_cli("sync", "vault").returncode == 0

    catalog = helpers.read_catalog(workdir)
    assert helpers.current(catalog["episodes"][0]["removed"]) is False
    assert helpers.current(catalog["streams"][0]["removed"]) is True


# Spec: Static | `published` | string | Original publication datetime |
# Context: static fields are not tracked; later source payloads do not rewrite
#          them. See AMBIGUITIES.md T13.
def test_static_fields_keep_first_observed_values(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry(
        "e1", published="2024-05-01T08:30:00", width=1920, height=1080)]))
    assert run_cli("sync", "vault").returncode == 0

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry(
        "e1", published="2024-06-09T01:02:03", width=640, height=360)]))
    assert run_cli("sync", "vault").returncode == 0

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["published"] == "2024-05-01T08:30:00"
    assert entry["width"] == 1920
    assert entry["height"] == 1080
    # and no history object was created for them
    for field in ("published", "width", "height"):
        assert not isinstance(entry[field], dict)
