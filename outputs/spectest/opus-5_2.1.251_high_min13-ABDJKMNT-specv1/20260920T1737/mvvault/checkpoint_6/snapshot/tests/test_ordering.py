"""Spec section: `catalog.json` Ordering / determinism of entry order."""

from conftest import read_catalog, source_entry


def sync(run_cli):
    result = run_cli("sync", "demo")
    assert result.returncode == 0, result.stderr


def ids(catalog, category="episodes"):
    return [entry["id"] for entry in catalog[category]]


# Phrase: "Sort Key Priority `1` | Newest `published` first"
def test_newest_published_first(run_cli, source, vault):
    source.serve(
        episodes=[
            source_entry("old", published="2020-01-01T00:00:00"),
            source_entry("new", published="2024-06-01T00:00:00"),
            source_entry("mid", published="2022-03-01T00:00:00"),
        ]
    )
    sync(run_cli)
    assert ids(read_catalog(vault)) == ["new", "mid", "old"]


# Phrase: "Sort Key Priority `2` | Lexicographically smaller `id` first when `published` values are equal"
def test_equal_published_breaks_ties_by_id(run_cli, source, vault):
    source.serve(
        episodes=[
            source_entry("b", published="2024-01-01T00:00:00"),
            source_entry("a", published="2024-01-01T00:00:00"),
            source_entry("C", published="2024-01-01T00:00:00"),
        ]
    )
    sync(run_cli)
    assert ids(read_catalog(vault)) == ["C", "a", "b"]


# Phrase: "Newest `published` first" - ordering is by time, not by text of mixed formats
def test_date_only_and_datetime_values_order_together(run_cli, source, vault):
    source.serve(
        episodes=[
            source_entry("dateonly", published="2024-05-02"),
            source_entry("early", published="2024-05-01T23:59:59"),
            source_entry("later", published="2024-05-02T00:00:01"),
        ]
    )
    sync(run_cli)
    assert ids(read_catalog(vault)) == ["later", "dateonly", "early"]


# Phrase: "Entry order | Newest `published` first" - applied per category
def test_each_category_is_sorted_independently(run_cli, source, vault):
    source.serve(
        episodes=[source_entry("e-old", published="2020-01-01"), source_entry("e-new", published="2024-01-01")],
        streams=[source_entry("s-old", published="2019-01-01"), source_entry("s-new", published="2023-01-01")],
        clips=[source_entry("c-old", published="2018-01-01"), source_entry("c-new", published="2022-01-01")],
    )
    sync(run_cli)
    catalog = read_catalog(vault)
    assert ids(catalog, "episodes") == ["e-new", "e-old"]
    assert ids(catalog, "streams") == ["s-new", "s-old"]
    assert ids(catalog, "clips") == ["c-new", "c-old"]


# Phrase: "Entry order" - order is maintained as entries are added across syncs
def test_new_entries_are_inserted_in_order(run_cli, source, vault):
    source.serve(episodes=[source_entry("b", published="2022-01-01")])
    sync(run_cli)
    source.serve(
        episodes=[
            source_entry("b", published="2022-01-01"),
            source_entry("a", published="2024-01-01"),
            source_entry("c", published="2020-01-01"),
        ]
    )
    sync(run_cli)
    assert ids(read_catalog(vault)) == ["a", "b", "c"]


# Phrase: "Removal handling | Never delete entry" - removed entries stay in sorted position
def test_removed_entries_keep_their_sorted_position(run_cli, source, vault):
    source.serve(
        episodes=[
            source_entry("a", published="2024-01-01"),
            source_entry("b", published="2023-01-01"),
            source_entry("c", published="2022-01-01"),
        ]
    )
    sync(run_cli)
    source.serve(episodes=[source_entry("a", published="2024-01-01"), source_entry("c", published="2022-01-01")])
    sync(run_cli)
    assert ids(read_catalog(vault)) == ["a", "b", "c"]
