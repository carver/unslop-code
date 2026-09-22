"""Spec section: Sorting (plus null ordering from Casting & Validation)."""
from conftest import body, header


# Phrase: "Sort by composite key specified via `--key` (one or more columns)"
# Context: Sorting.
def test_composite_key_orders_by_first_then_second(run, work):
    work.csv(
        "a.csv", ["g", "id", "v"],
        [["b", "2", "p"], ["a", "2", "q"], ["b", "1", "r"], ["a", "1", "s"]],
    )
    r = run("--output", "-", "--key", "g,id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[:2] for row in body(r)] == [
        ["a", "1"], ["a", "2"], ["b", "1"], ["b", "2"],
    ]


# Phrase: "Default order is ascending"
# Context: Sorting.
def test_default_order_is_ascending(run, work):
    work.csv("a.csv", ["id"], [["3"], ["1"], ["2"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["2"], ["3"]]


# Phrase: "`--desc` applies to all keys"
# Context: Sorting; every key column is reversed, not just the first.
def test_desc_reverses_all_keys(run, work):
    work.csv(
        "a.csv", ["g", "id"],
        [["a", "1"], ["a", "2"], ["b", "1"], ["b", "2"]],
    )
    r = run("--output", "-", "--key", "g,id", "--desc", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["b", "2"], ["b", "1"], ["a", "2"], ["a", "1"]]


# Phrase: "Sort must be stable with respect to input appearance for equal keys"
# Context: Sorting; ties keep within-file order and command-line file order.
def test_stability_within_a_file(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "first"], ["1", "second"], ["1", "third"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["first", "second", "third"]


def test_stability_across_files_follows_argument_order(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "a1"], ["1", "a2"]])
    work.csv("b.csv", ["id", "v"], [["1", "b1"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"), work.path("b.csv"))
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["a1", "a2", "b1"]


def test_stability_across_files_reversed_argument_order(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "a1"]])
    work.csv("b.csv", ["id", "v"], [["1", "b1"]])
    r = run("--output", "-", "--key", "id", work.path("b.csv"), work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["b1", "a1"]


# Phrase: "Sort must be stable ... for equal keys" combined with "--desc"
# Context: Sorting; --desc reverses key order but not tie order.
def test_stability_is_preserved_under_desc(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "x"], ["1", "y"], ["2", "z"]])
    r = run("--output", "-", "--key", "id", "--desc", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["2", "z"], ["1", "x"], ["1", "y"]]


# Phrase: "Nulls always compare less than non-null values ... (first in ascending)"
# Context: Casting & Validation.
def test_nulls_sort_first_ascending(run, work):
    work.csv("a.csv", ["id", "v"], [["2", "b"], ["", "n"], ["1", "a"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["n", "a", "b"]


# Phrase: "...regardless of sort direction (... last in descending)"
# Context: Casting & Validation.
def test_nulls_sort_last_descending(run, work):
    work.csv("a.csv", ["id", "v"], [["2", "b"], ["", "n"], ["1", "a"]])
    r = run("--output", "-", "--key", "id", "--desc", work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["b", "a", "n"]


# Phrase: "Nulls always compare less than non-null values"
# Context: Casting & Validation; a column absent from one file is null for its rows.
def test_missing_column_rows_sort_as_nulls(run, work):
    work.csv("a.csv", ["id", "k"], [["1", "5"]])
    work.csv("b.csv", ["id"], [["2"]])
    r = run("--output", "-", "--key", "k", work.path("a.csv"), work.path("b.csv"))
    assert r.ok, r.stderr
    assert [row[header(r).index("id")] for row in body(r)] == ["2", "1"]


# Phrase: "Sort by composite key" with nulls in a secondary key
# Context: Casting & Validation; null ordering applies per key column.
def test_nulls_in_secondary_key(run, work):
    work.csv("a.csv", ["g", "id"], [["a", "2"], ["a", ""], ["a", "1"]])
    r = run("--output", "-", "--key", "g,id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["", "1", "2"]


# Phrase: "sorted globally by the key(s)"
# Context: Sorting; numeric columns sort numerically, not lexicographically.
def test_int_key_sorts_numerically(run, work):
    work.csv("a.csv", ["id"], [["10"], ["9"], ["100"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["9"], ["10"], ["100"]]


def test_string_key_sorts_lexicographically(run, work):
    work.csv("a.csv", ["id"], [["b10"], ["b9"], ["a1"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["a1"], ["b10"], ["b9"]]


# Phrase: "sorted globally by the key(s)" for temporal keys
# Context: Sorting; timestamps sort chronologically across zones.
def test_timestamp_key_sorts_chronologically(run, work):
    work.schema("s.json", [("ts", "timestamp"), ("v", "string")])
    work.csv(
        "a.csv", ["ts", "v"],
        [["2024-07-01T12:00:00+02:00", "later"], ["2024-07-01T09:00:00Z", "earlier"]],
    )
    r = run(
        "--output", "-", "--key", "ts", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["earlier", "later"]


# Phrase: "Tool must handle inputs exceeding `--memory-limit-mb` constraint"
# Context: Sorting; correctness is unaffected by chunking.
def test_sort_correct_under_tiny_memory_limit(run, work):
    rows = [[str((i * 37) % 500)] for i in range(500)]
    work.csv("a.csv", ["id"], rows)
    r = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "1", work.path("a.csv")
    )
    assert r.ok, r.stderr
    got = [int(row[0]) for row in body(r)]
    assert got == sorted(int(x[0]) for x in rows)
