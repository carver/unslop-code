"""Global ordering: composite keys, direction, stability and null placement."""

from conftest import column, rows_of


# Spec: "all rows from inputs, sorted globally by the key(s)"
# Context: ordering spans files, it is not a per-file sort concatenated.
def test_rows_are_sorted_globally_across_files(make_csv, run):
    make_csv("a.csv", "id\n5\n1\n")
    make_csv("b.csv", "id\n3\n2\n")
    proc = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert column(rows_of(proc.stdout), "id") == ["1", "2", "3", "5"]


# Spec: "Sort by composite key specified via `--key` (one or more columns)"
def test_composite_key_sorts_by_first_column_then_second(make_csv, run):
    make_csv("a.csv", "g,id\nb,1\na,2\nb,0\na,1\n")
    proc = run("--output", "-", "--key", "g,id", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["a", "1"], ["a", "2"], ["b", "0"], ["b", "1"]]


# Spec: "Default order is ascending"
def test_default_order_is_ascending(make_csv, run):
    make_csv("a.csv", "id\n3\n1\n2\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert column(rows_of(proc.stdout), "id") == ["1", "2", "3"]


# Spec: "`--desc` applies to all keys"
def test_desc_reverses_every_key_of_a_composite_sort(make_csv, run):
    make_csv("a.csv", "g,id\na,1\nb,2\na,2\nb,1\n")
    proc = run("--output", "-", "--key", "g,id", "--desc", "a.csv")
    assert rows_of(proc.stdout)[1:] == [["b", "2"], ["b", "1"], ["a", "2"], ["a", "1"]]


# Spec: "Sort must be stable with respect to input appearance for equal keys"
# Context: ties keep command-line file order first, then row order inside a file.
def test_equal_keys_keep_input_appearance_order(make_csv, run):
    make_csv("a.csv", "id,src\n7,a1\n7,a2\n")
    make_csv("b.csv", "id,src\n7,b1\n7,b2\n")
    proc = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert column(rows_of(proc.stdout), "src") == ["a1", "a2", "b1", "b2"]


# Spec: "Sort must be stable ... for equal keys" combined with "`--desc` applies to all keys"
# Context: reversing the direction must not reverse tie order.
def test_stability_is_preserved_under_desc(make_csv, run):
    make_csv("a.csv", "id,src\n7,a1\n7,a2\n")
    make_csv("b.csv", "id,src\n7,b1\n")
    proc = run("--output", "-", "--key", "id", "--desc", "a.csv", "b.csv")
    assert column(rows_of(proc.stdout), "src") == ["a1", "a2", "b1"]


# Spec: "Nulls always compare less than non-null values ... (first in ascending)"
def test_nulls_sort_first_when_ascending(make_csv, run):
    make_csv("a.csv", "id,note\n2,x\n,y\n1,z\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert column(rows_of(proc.stdout), "note") == ["y", "z", "x"]


# Spec: "Nulls always compare less than non-null values, regardless of sort direction (... last in descending)"
def test_nulls_sort_last_when_descending(make_csv, run):
    make_csv("a.csv", "id,note\n2,x\n,y\n1,z\n")
    proc = run("--output", "-", "--key", "id", "--desc", "a.csv")
    assert column(rows_of(proc.stdout), "note") == ["x", "z", "y"]


# Spec: "sorted globally by the key(s)" with "int" typing
# Context: an int key orders numerically rather than lexicographically.
def test_int_keys_order_numerically(make_csv, run):
    make_csv("a.csv", "id\n10\n9\n100\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert column(rows_of(proc.stdout), "id") == ["9", "10", "100"]


# Spec: "timestamp: ISO-8601 format" used as a sort key
# Context: instants order chronologically, across differing zone offsets.
def test_timestamp_keys_order_chronologically_across_offsets(make_csv, make_schema, run):
    make_csv("a.csv", "ts,id\n2024-07-01T12:00:00+02:00,late\n2024-07-01T09:00:00Z,early\n")
    make_schema("s.json", [("ts", "timestamp"), ("id", "string")])
    proc = run("--output", "-", "--key", "ts", "--schema", "s.json", "a.csv")
    assert column(rows_of(proc.stdout), "id") == ["early", "late"]


# Spec: "If a key column is not present in resolved schema, that is an error"
def test_unknown_key_column_is_an_error(make_csv, run):
    make_csv("a.csv", "id\n1\n")
    proc = run("--output", "-", "--key", "missing", "a.csv", expect_ok=False)
    assert proc.returncode != 0
    assert "missing" in proc.stderr


# Spec: "If a key column is not present in resolved schema, that is an error"
# Context: the resolved schema is the provided one, so a column that exists only
# in the input but not in the schema is still an error.
def test_key_present_in_input_but_absent_from_schema_is_an_error(make_csv, make_schema, run):
    make_csv("a.csv", "id,note\n1,x\n")
    make_schema("s.json", [("id", "int")])
    proc = run("--output", "-", "--key", "note", "--schema", "s.json", "a.csv", expect_ok=False)
    assert proc.returncode != 0
