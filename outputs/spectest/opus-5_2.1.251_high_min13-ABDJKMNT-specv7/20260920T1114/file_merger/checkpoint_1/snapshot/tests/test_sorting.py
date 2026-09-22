"""Spec section: Sorting — key selection, direction, stability, null placement."""

from conftest import column, rows_of


# Phrase: "sorted globally by the key(s)"
# Context: Sorting. Order spans all inputs, not just within a file.
def test_sort_is_global_across_files(csv_file, run_tool):
    csv_file("a.csv", "id\n5\n1\n")
    csv_file("b.csv", "id\n3\n2\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert column(result.stdout, "id") == ["1", "2", "3", "5"]


# Phrase: "Sort by composite key specified via --key (one or more columns)"
# Context: Sorting. Later key columns break ties in earlier ones.
def test_composite_key_orders_by_each_column_in_turn(csv_file, run_tool):
    csv_file("a.csv", "grp,id\nb,2\na,2\nb,1\na,1\n")
    result = run_tool("--output", "-", "--key", "grp,id", "a.csv")
    assert rows_of(result.stdout) == [["a", "1"], ["a", "2"], ["b", "1"], ["b", "2"]]


# Phrase: "Default order is ascending"
# Context: Sorting.
def test_default_order_is_ascending(csv_file, run_tool):
    csv_file("a.csv", "id\n3\n1\n2\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert column(result.stdout, "id") == ["1", "2", "3"]


# Phrase: "--desc applies to all keys"
# Context: Sorting. Both key columns reverse together.
def test_desc_reverses_every_key_column(csv_file, run_tool):
    csv_file("a.csv", "grp,id\na,1\nb,2\na,2\nb,1\n")
    result = run_tool("--output", "-", "--key", "grp,id", "--desc", "a.csv")
    assert rows_of(result.stdout) == [["b", "2"], ["b", "1"], ["a", "2"], ["a", "1"]]


# Phrase: "Sort must be stable with respect to input appearance for equal keys"
# Context: Sorting. Ties keep file order, then row order within a file.
def test_equal_keys_keep_input_appearance_order(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,a1\n1,a2\n")
    csv_file("b.csv", "id,note\n1,b1\n1,b2\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert column(result.stdout, "note") == ["a1", "a2", "b1", "b2"]


# Phrase: "Sort must be stable with respect to input appearance for equal keys"
# Context: Sorting, combined with --desc. Ambiguity T19: ties are not reversed.
def test_stability_holds_under_desc(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,a1\n2,a2\n1,a3\n")
    csv_file("b.csv", "id,note\n1,b1\n")
    result = run_tool("--output", "-", "--key", "id", "--desc", "a.csv", "b.csv")
    assert column(result.stdout, "note") == ["a2", "a1", "a3", "b1"]


# Phrase: "Nulls always compare less than non-null values ... (first in ascending)"
# Context: Casting & Validation.
def test_nulls_sort_first_when_ascending(csv_file, run_tool):
    csv_file("a.csv", "id,note\n2,b\n,n\n1,a\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert column(result.stdout, "note") == ["n", "a", "b"]


# Phrase: "Nulls always compare less than non-null values ... (last in descending)"
# Context: Casting & Validation.
def test_nulls_sort_last_when_descending(csv_file, run_tool):
    csv_file("a.csv", "id,note\n2,b\n,n\n1,a\n")
    result = run_tool("--output", "-", "--key", "id", "--desc", "a.csv")
    assert column(result.stdout, "note") == ["b", "a", "n"]


# Phrase: "Nulls always compare less than non-null values"
# Context: Casting & Validation. Null in the first key column of a composite key.
def test_null_in_leading_key_column_sorts_first(csv_file, run_tool):
    csv_file("a.csv", "grp,id\nb,1\n,9\na,1\n")
    result = run_tool("--output", "-", "--key", "grp,id", "a.csv")
    assert rows_of(result.stdout) == [["", "9"], ["a", "1"], ["b", "1"]]


# Phrase: "sorted globally by the key(s)"
# Context: Sorting. Numeric keys sort numerically, not as text.
def test_int_keys_sort_numerically(csv_file, run_tool):
    csv_file("a.csv", "id\n10\n9\n100\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert column(result.stdout, "id") == ["9", "10", "100"]


# Phrase: "sorted globally by the key(s)"
# Context: Sorting. String keys sort lexicographically.
def test_string_keys_sort_lexicographically(csv_file, run_tool):
    csv_file("a.csv", "name\nbanana\nApple\ncherry\n")
    result = run_tool("--output", "-", "--key", "name", "a.csv")
    assert column(result.stdout, "name") == ["Apple", "banana", "cherry"]


# Phrase: "sorted globally by the key(s)"
# Context: Sorting. Timestamp keys sort chronologically across zone offsets.
def test_timestamp_keys_sort_chronologically(csv_file, run_tool):
    csv_file(
        "a.csv",
        "ts,note\n2024-07-01T12:00:00+02:00,later\n2024-07-01T09:00:00Z,earlier\n",
    )
    csv_file("schema.json", '{"columns": [{"name": "ts", "type": "timestamp"}, {"name": "note", "type": "string"}]}')
    result = run_tool("--output", "-", "--key", "ts", "--schema", "schema.json", "a.csv")
    assert column(result.stdout, "note") == ["earlier", "later"]


# Phrase: "Sort by composite key specified via --key"
# Context: Sorting. Keys may be listed in any order relative to the schema.
def test_key_order_is_independent_of_column_order(csv_file, run_tool):
    csv_file("a.csv", "grp,id\na,2\nb,1\na,1\n")
    result = run_tool("--output", "-", "--key", "id,grp", "a.csv")
    assert rows_of(result.stdout) == [["a", "1"], ["b", "1"], ["a", "2"]]


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: Casting & Validation, inferred schema.
def test_unknown_key_column_is_an_error(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "missing", "a.csv")
    assert result.returncode != 0
    assert "missing" in result.stderr


# Phrase: "If a key column is not present in resolved schema, that is an error"
# Context: Casting & Validation. A column dropped by the schema cannot be a key.
def test_key_column_outside_provided_schema_is_an_error(csv_file, run_tool):
    csv_file("a.csv", "id,extra\n1,x\n")
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}]}')
    result = run_tool("--output", "-", "--key", "extra", "--schema", "schema.json", "a.csv")
    assert result.returncode != 0
    assert "extra" in result.stderr
