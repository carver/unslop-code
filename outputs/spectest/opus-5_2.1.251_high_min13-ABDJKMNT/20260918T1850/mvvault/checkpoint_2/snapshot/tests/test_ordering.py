"""Spec section: `catalog.json` Ordering."""

import pytest

from conftest import payload, read_catalog, source_entry


def ids(catalog, category="episodes"):
    return [entry["id"] for entry in catalog[category]]


# Spec: Sort Key Priority `1` | Newest `published` first
def test_entries_are_sorted_newest_published_first(run, source, vault):
    source.serve(
        payload(
            episodes=[
                source_entry("old", published="2020-01-01T00:00:00"),
                source_entry("new", published="2024-01-01T00:00:00"),
                source_entry("mid", published="2022-06-15T12:30:00"),
            ]
        )
    )
    run("sync", "vault")
    assert ids(read_catalog(vault)) == ["new", "mid", "old"]


# Spec: Sort Key Priority `2` | Lexicographically smaller `id` first when
# `published` values are equal
def test_equal_published_breaks_ties_by_id(run, source, vault):
    same = "2024-01-01T00:00:00"
    source.serve(
        payload(
            episodes=[
                source_entry("banana", published=same),
                source_entry("apple", published=same),
                source_entry("Cherry", published=same),
            ]
        )
    )
    run("sync", "vault")
    assert ids(read_catalog(vault)) == ["Cherry", "apple", "banana"]


# Spec: Entry order | Newest `published` first; ties break by lexicographically smaller `id`
def test_ordering_applies_to_every_category(run, source, vault):
    entries = [
        source_entry("b", published="2021-01-01T00:00:00"),
        source_entry("a", published="2023-01-01T00:00:00"),
    ]
    source.serve(payload(episodes=entries, streams=entries, clips=entries))
    run("sync", "vault")

    catalog = read_catalog(vault)
    for category in ("episodes", "streams", "clips"):
        assert ids(catalog, category) == ["a", "b"]


# Spec: Sort Key Priority `1` | Newest `published` first (date-only sorts by normalized value)
def test_date_only_and_datetime_sort_together(run, source, vault):
    source.serve(
        payload(
            episodes=[
                source_entry("dateonly", published="2024-03-05"),
                source_entry("sameday", published="2024-03-05T09:00:00"),
                source_entry("dayafter", published="2024-03-06"),
            ]
        )
    )
    run("sync", "vault")
    assert ids(read_catalog(vault)) == ["dayafter", "sameday", "dateonly"]


# Spec: Entry order ... (removed entries stay in the same ordering)
def test_removed_entries_keep_their_sorted_position(run, source, vault):
    newer = source_entry("newer", published="2024-01-01T00:00:00")
    older = source_entry("older", published="2020-01-01T00:00:00")
    source.serve(payload(episodes=[newer, older]))
    run("sync", "vault")

    source.serve(payload(episodes=[older]))
    run("sync", "vault")
    assert ids(read_catalog(vault)) == ["newer", "older"]


# Spec: Entry order ... (ordering is re-established as entries arrive over time)
def test_ordering_survives_incremental_syncs(run, source, vault):
    source.serve(payload(episodes=[source_entry("m", published="2022-01-01T00:00:00")]))
    run("sync", "vault")
    source.serve(
        payload(
            episodes=[
                source_entry("m", published="2022-01-01T00:00:00"),
                source_entry("z", published="2023-01-01T00:00:00"),
                source_entry("a", published="2021-01-01T00:00:00"),
            ]
        )
    )
    run("sync", "vault")
    assert ids(read_catalog(vault)) == ["z", "m", "a"]


# Spec: Entry order ... (a stored catalog written out of order is re-sorted)
@pytest.mark.parametrize("reverse", [True, False])
def test_stored_order_is_canonicalized(run, source, vault, reverse):
    import json

    entries = [
        source_entry("a", published="2023-01-01T00:00:00"),
        source_entry("b", published="2021-01-01T00:00:00"),
    ]
    source.serve(payload(episodes=entries))
    run("sync", "vault")

    catalog = read_catalog(vault)
    catalog["episodes"] = sorted(catalog["episodes"], key=lambda e: e["id"], reverse=reverse)
    (vault / "catalog.json").write_text(json.dumps(catalog))

    run("sync", "vault")
    assert ids(read_catalog(vault)) == ["a", "b"]
