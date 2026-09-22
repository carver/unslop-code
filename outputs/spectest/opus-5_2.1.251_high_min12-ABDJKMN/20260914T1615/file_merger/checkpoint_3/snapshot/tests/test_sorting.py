"""Spec section: Sorting (+ the null-ordering rule under Casting & Validation)."""

from conftest import body, col, run_ok, write, write_schema


# --- Spec: "sorted globally by the key(s)" ---
# Context: Output. Rows from different files interleave by key, not by file.
def test_global_sort_across_files(ws):
    a = write(ws / "a.csv", "id,src\n1,a\n5,a\n")
    b = write(ws / "b.csv", "id,src\n3,b\n7,b\n")
    c = write(ws / "c.csv", "id,src\n2,c\n6,c\n")
    res = run_ok("--output", "-", "--key", "id", a, b, c)
    assert col(res.stdout, "id") == ["1", "2", "3", "5", "6", "7"]


# --- Spec: "Sort by composite key specified via `--key` (one or more columns)" ---
# Context: Sorting. Comma-separated column list, leftmost is most significant.
def test_composite_key_leftmost_most_significant(ws):
    a = write(ws / "a.csv", "g,id\n2,1\n1,2\n1,1\n2,0\n")
    res = run_ok("--output", "-", "--key", "g,id", a)
    assert body(res.stdout) == ["1,1", "1,2", "2,0", "2,1"]


# --- Spec: "Default order is ascending" ---
# Context: Sorting.
def test_default_order_is_ascending(ws):
    a = write(ws / "a.csv", "id\n3\n1\n2\n")
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "id") == ["1", "2", "3"]


# --- Spec: "`--desc` applies to all keys" ---
# Context: Sorting. Every key column reverses, not just the first.
def test_desc_applies_to_all_keys(ws):
    a = write(ws / "a.csv", "g,id\n1,1\n1,2\n2,1\n2,2\n")
    res = run_ok("--output", "-", "--key", "g,id", "--desc", a)
    assert body(res.stdout) == ["2,2", "2,1", "1,2", "1,1"]


# --- Spec: "Sort must be stable with respect to input appearance for equal keys" ---
# Context: Sorting. Ties keep (file order on the command line, then row order).
def test_stable_for_equal_keys(ws):
    a = write(ws / "a.csv", "k,tag\n7,a1\n7,a2\n")
    b = write(ws / "b.csv", "k,tag\n7,b1\n7,b2\n")
    res = run_ok("--output", "-", "--key", "k", a, b)
    assert col(res.stdout, "tag") == ["a1", "a2", "b1", "b2"]


# --- Spec: "stable with respect to input appearance" follows argv order ---
# Context: Sorting. Swapping the two inputs swaps the tie order.
def test_stability_follows_command_line_order(ws):
    a = write(ws / "a.csv", "k,tag\n7,a1\n")
    b = write(ws / "b.csv", "k,tag\n7,b1\n")
    res = run_ok("--output", "-", "--key", "k", b, a)
    assert col(res.stdout, "tag") == ["b1", "a1"]


# --- Spec: "Sort must be stable ... for equal keys" holds under `--desc` too ---
# Context: Sorting; see AMBIGUITIES T13 (tiebreak stays ascending).
def test_stability_preserved_under_desc(ws):
    a = write(ws / "a.csv", "k,tag\n1,a1\n1,a2\n3,a3\n")
    b = write(ws / "b.csv", "k,tag\n1,b1\n")
    res = run_ok("--output", "-", "--key", "k", "--desc", a, b)
    assert col(res.stdout, "tag") == ["a3", "a1", "a2", "b1"]


# --- Spec: sorting compares cast values, not emitted text ---
# Context: Casting & Validation + Sorting; see AMBIGUITIES T19.
def test_int_key_sorts_numerically_not_lexicographically(ws):
    a = write(ws / "a.csv", "id\n10\n9\n100\n")
    s = write_schema(ws / "s.json", [("id", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "id") == ["9", "10", "100"]


# --- Spec: float key columns order numerically ---
# Context: Casting & Validation + Sorting.
def test_float_key_sorts_numerically(ws):
    a = write(ws / "a.csv", "v\n2.5\n10.25\n-3\n")
    s = write_schema(ws / "s.json", [("v", "float")])
    res = run_ok("--output", "-", "--key", "v", "--schema", s, a)
    assert col(res.stdout, "v") == ["-3.0", "2.5", "10.25"]


# --- Spec: string key columns order lexicographically ---
# Context: Casting & Validation + Sorting.
def test_string_key_sorts_lexicographically(ws):
    a = write(ws / "a.csv", "s\nb\nA\na\nB\n")
    s = write_schema(ws / "s.json", [("s", "string")])
    res = run_ok("--output", "-", "--key", "s", "--schema", s, a)
    assert col(res.stdout, "s") == ["A", "B", "a", "b"]


# --- Spec: date key columns order chronologically ---
# Context: Casting & Validation + Sorting.
def test_date_key_sorts_chronologically(ws):
    a = write(ws / "a.csv", "d\n2024-12-01\n2024-02-09\n2023-12-31\n")
    s = write_schema(ws / "s.json", [("d", "date")])
    res = run_ok("--output", "-", "--key", "d", "--schema", s, a)
    assert col(res.stdout, "d") == ["2023-12-31", "2024-02-09", "2024-12-01"]


# --- Spec: timestamp key columns order chronologically across zones ---
# Context: Casting & Validation ("normalize to UTC") + Sorting.
def test_timestamp_key_sorts_chronologically_across_offsets(ws):
    a = write(ws / "a.csv",
              "ts\n2024-07-01T12:00:00Z\n2024-07-01T08:00:00-05:00\n"
              "2024-07-01T15:00:00+02:00\n")
    s = write_schema(ws / "s.json", [("ts", "timestamp")])
    res = run_ok("--output", "-", "--key", "ts", "--schema", s, a)
    assert col(res.stdout, "ts") == ["2024-07-01T12:00:00Z", "2024-07-01T13:00:00Z",
                                     "2024-07-01T13:00:00Z"]


# --- Spec: bool key columns order false < true ---
# Context: Casting & Validation + Sorting.
def test_bool_key_sorts_false_before_true(ws):
    a = write(ws / "a.csv", "b\ntrue\nfalse\n1\n0\n")
    s = write_schema(ws / "s.json", [("b", "bool")])
    res = run_ok("--output", "-", "--key", "b", "--schema", s, a)
    assert col(res.stdout, "b") == ["false", "false", "true", "true"]


# --- Spec: "Nulls always compare less than non-null values ... (first in ascending)" ---
# Context: Casting & Validation.
def test_nulls_first_ascending(ws):
    a = write(ws / "a.csv", "id\n2\n\n1\n")
    s = write_schema(ws / "s.json", [("id", "int")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "id") == ["", "1", "2"]


# --- Spec: "Nulls always compare less ... regardless of sort direction (last in descending)" ---
# Context: Casting & Validation.
def test_nulls_last_descending(ws):
    a = write(ws / "a.csv", "id\n2\n\n1\n")
    s = write_schema(ws / "s.json", [("id", "int")])
    res = run_ok("--output", "-", "--key", "id", "--desc", "--schema", s, a)
    assert col(res.stdout, "id") == ["2", "1", ""]


# --- Spec: null ordering applies per key column within a composite key ---
# Context: Casting & Validation + Sorting.
def test_null_ordering_within_composite_key(ws):
    a = write(ws / "a.csv", "g,id\n1,2\n1,\n,9\n")
    s = write_schema(ws / "s.json", [("g", "int"), ("id", "int")])
    res = run_ok("--output", "-", "--key", "g,id", "--schema", s, a)
    assert body(res.stdout) == [",9", "1,", "1,2"]


# --- Spec: null ordering for string key columns too ---
# Context: Casting & Validation; a missing cell is a null, and nulls sort first.
def test_nulls_first_for_string_key(ws):
    a = write(ws / "a.csv", "s\nb\n\na\n")
    res = run_ok("--output", "-", "--key", "s", a)
    assert col(res.stdout, "s") == ["", "a", "b"]


# --- Spec: "Missing input columns filled with null literal" and sort as nulls ---
# Context: Schema Resolution + null ordering; see AMBIGUITIES T20.
def test_key_column_absent_from_one_file_sorts_as_null(ws):
    a = write(ws / "a.csv", "id,k\n1,5\n")
    b = write(ws / "b.csv", "id\n2\n")
    res = run_ok("--output", "-", "--key", "k", a, b)
    assert col(res.stdout, "id") == ["2", "1"]


# --- Spec: "--key <col>[,<col>...]" accepts three or more columns ---
# Context: Usage / Sorting.
def test_three_column_composite_key(ws):
    a = write(ws / "a.csv", "a,b,c\n5,4,2\n5,4,1\n5,3,9\n2,9,9\n")
    res = run_ok("--output", "-", "--key", "a,b,c", a)
    assert body(res.stdout) == ["2,9,9", "5,3,9", "5,4,1", "5,4,2"]
