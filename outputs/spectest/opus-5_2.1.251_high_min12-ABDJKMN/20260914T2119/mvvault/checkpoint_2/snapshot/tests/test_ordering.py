"""Spec: `catalog.json` Ordering (and the matching Determinism row)."""
import pytest

from conftest import make_entry, read_catalog


def ids(catalog, category="episodes"):
    return [e["id"] for e in catalog[category]]


# Spec: "| `1` | Newest `published` first |"
def test_newest_published_first(run, source, tmp_path, vault):
    source.serve(episodes=[
        make_entry(id="old", published="2020-01-01T00:00:00"),
        make_entry(id="new", published="2024-01-01T00:00:00"),
        make_entry(id="mid", published="2022-06-15T08:30:00"),
    ])
    run("sync", "vault")
    assert ids(read_catalog(tmp_path)) == ["new", "mid", "old"]


# Spec: "| `2` | Lexicographically smaller `id` first when `published` values
# are equal |"
def test_ties_break_on_lexicographically_smaller_id(run, source, tmp_path, vault):
    same = "2024-01-01T00:00:00"
    source.serve(episodes=[
        make_entry(id="b", published=same),
        make_entry(id="C", published=same),
        make_entry(id="a", published=same),
        make_entry(id="A", published=same),
    ])
    run("sync", "vault")
    # Lexicographic (codepoint) order: uppercase sorts before lowercase.
    assert ids(read_catalog(tmp_path)) == ["A", "C", "a", "b"]


# Spec: sort key priority 1 then 2 -- published dominates the id tiebreak.
def test_published_dominates_id(run, source, tmp_path, vault):
    source.serve(episodes=[
        make_entry(id="zzz", published="2025-01-01T00:00:00"),
        make_entry(id="aaa", published="2024-01-01T00:00:00"),
    ])
    run("sync", "vault")
    assert ids(read_catalog(tmp_path)) == ["zzz", "aaa"]


# Spec: "| Entry order | Newest `published` first; ties break by
# lexicographically smaller `id` |" -- ordering applies to every category.
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_ordering_applies_to_every_category(run, source, tmp_path, vault, category):
    source.serve(**{category: [
        make_entry(id="a", published="2020-01-01T00:00:00"),
        make_entry(id="b", published="2021-01-01T00:00:00"),
    ]})
    run("sync", "vault")
    assert ids(read_catalog(tmp_path), category) == ["b", "a"]


# Spec: ordering is a property of the stored catalog, so source order is
# irrelevant and re-syncing keeps the order stable.
def test_ordering_is_independent_of_source_order(run, source, tmp_path, vault):
    entries = [
        make_entry(id="m", published="2022-01-01T00:00:00"),
        make_entry(id="z", published="2023-01-01T00:00:00"),
        make_entry(id="a", published="2021-01-01T00:00:00"),
    ]
    source.serve(episodes=entries)
    run("sync", "vault")
    first = ids(read_catalog(tmp_path))
    source.serve(episodes=list(reversed(entries)))
    run("sync", "vault")
    assert ids(read_catalog(tmp_path)) == first == ["z", "m", "a"]


# Spec: "Removal handling | Never delete entry" + ordering -- removed entries
# stay in place in the sorted order.
def test_removed_entries_keep_their_sorted_position(run, source, tmp_path, vault):
    source.serve(episodes=[
        make_entry(id="new", published="2024-01-01T00:00:00"),
        make_entry(id="old", published="2020-01-01T00:00:00"),
    ])
    run("sync", "vault")
    source.serve(episodes=[make_entry(id="old", published="2020-01-01T00:00:00")])
    run("sync", "vault")
    assert ids(read_catalog(tmp_path)) == ["new", "old"]


# Spec: ordering must hold after entries are added across several syncs.
def test_ordering_after_incremental_additions(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="b", published="2022-01-01T00:00:00")])
    run("sync", "vault")
    source.serve(episodes=[
        make_entry(id="b", published="2022-01-01T00:00:00"),
        make_entry(id="a", published="2023-01-01T00:00:00"),
        make_entry(id="c", published="2021-01-01T00:00:00"),
    ])
    run("sync", "vault")
    assert ids(read_catalog(tmp_path)) == ["a", "b", "c"]


# Spec: Ordering key 1 uses `published`, which for date-only source values is
# normalized to `00:00:00`, so dates and datetimes compare consistently.
def test_ordering_mixes_date_only_and_datetime_values(run, source, tmp_path, vault):
    source.serve(episodes=[
        make_entry(id="dateonly", published="2024-03-02"),
        make_entry(id="earlier", published="2024-03-01T23:59:59"),
        make_entry(id="later", published="2024-03-02T00:00:01"),
    ])
    run("sync", "vault")
    assert ids(read_catalog(tmp_path)) == ["later", "dateonly", "earlier"]
