"""Spec section: Sorting (plus the null ordering rule)."""
from conftest import run_tool, write_csv, write_schema, col


# Phrase: "Sort by composite key specified via --key (one or more columns)"
# Context: one column.
def test_single_column_key(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "3", "1", "2"])
    assert col(run_tool("--output", "-", "--key", "id", src).rows(), "id") \
        == ["1", "2", "3"]


# Phrase: "Sort by composite key specified via --key (one or more columns)"
# Context: the second key breaks ties on the first.
def test_composite_key_second_breaks_ties(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["g,n", "b,1", "a,2", "a,1", "b,0"])
    rows = run_tool("--output", "-", "--key", "g,n", src).rows()[1:]
    assert rows == [["a", "1"], ["a", "2"], ["b", "0"], ["b", "1"]]


# Phrase: "Default order is ascending"
# Context: no --desc flag.
def test_default_order_is_ascending(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "10", "2", "1"])
    # inferred as int, so numeric (not lexicographic) ascending order
    assert col(run_tool("--output", "-", "--key", "id", src).rows(), "id") \
        == ["1", "2", "10"]


# Phrase: "--desc applies to all keys"
# Context: every key column is reversed, not just the first.
def test_desc_applies_to_all_keys(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["g,n", "a,1", "a,2", "b,1", "b,2"])
    rows = run_tool("--output", "-", "--key", "g,n", "--desc", src).rows()[1:]
    assert rows == [["b", "2"], ["b", "1"], ["a", "2"], ["a", "1"]]


# Phrase: "Sort must be stable with respect to input appearance for equal keys"
# Context: rows with equal keys keep their order within one file.
def test_stability_within_a_file(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["k,tag", "1,first", "1,second", "1,third"])
    rows = run_tool("--output", "-", "--key", "k", src).rows()[1:]
    assert [r[1] for r in rows] == ["first", "second", "third"]


# Phrase: "stable with respect to input appearance"
# Context: across files, the command-line order of inputs is the appearance
# order.
def test_stability_across_files_follows_argument_order(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["k,tag", "1,a1", "1,a2"])
    b = write_csv(tmp_path / "b.csv", ["k,tag", "1,b1"])
    rows = run_tool("--output", "-", "--key", "k", a, b).rows()[1:]
    assert [r[1] for r in rows] == ["a1", "a2", "b1"]
    rows = run_tool("--output", "-", "--key", "k", b, a).rows()[1:]
    assert [r[1] for r in rows] == ["b1", "a1", "a2"]


# Phrase: "Sort must be stable ... for equal keys" + "--desc"
# Context: descending reverses key order but equal keys keep appearance order.
def test_stability_preserved_under_desc(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["k,tag", "1,first", "1,second", "2,other"])
    rows = run_tool("--output", "-", "--key", "k", "--desc", src).rows()[1:]
    assert rows == [["2", "other"], ["1", "first"], ["1", "second"]]


# Phrase: "Nulls always compare less than non-null values ... first in ascending"
# Context: ascending puts nulls at the top.
def test_nulls_first_ascending(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["k,v", "2,b", ",n", "1,a"])
    rows = run_tool("--output", "-", "--key", "k", src).rows()[1:]
    assert rows[0] == ["", "n"]


# Phrase: "Nulls always compare less than non-null values, regardless of sort
#          direction ... last in descending"
# Context: descending puts nulls at the bottom.
def test_nulls_last_descending(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["k,v", "2,b", ",n", "1,a"])
    rows = run_tool("--output", "-", "--key", "k", "--desc", src).rows()[1:]
    assert rows[-1] == ["", "n"]
    assert rows[0] == ["2", "b"]


# Phrase: "Nulls always compare less than non-null values"
# Context: a column missing from a whole file is null for those rows.
def test_missing_column_sorts_as_null(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,k", "1,5"])
    b = write_csv(tmp_path / "b.csv", ["id", "2"])
    rows = run_tool("--output", "-", "--key", "k", a, b).rows()[1:]
    assert rows[0][0] == "2"


# Phrase: "Nulls always compare less" with a composite key
# Context: nullness is evaluated per key component.
def test_null_ordering_within_composite_key(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["g,n", "a,2", "a,", "a,1"])
    rows = run_tool("--output", "-", "--key", "g,n", src).rows()[1:]
    assert [r[1] for r in rows] == ["", "1", "2"]


# Phrase: "sorted globally by the key(s)" for typed columns
# Context: a date key sorts chronologically.
def test_date_key_sorts_chronologically(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["d", "2024-12-01", "2024-02-09", "2023-11-30"])
    rows = run_tool("--output", "-", "--key", "d", src).rows()[1:]
    assert [r[0] for r in rows] == ["2023-11-30", "2024-02-09", "2024-12-01"]


# Phrase: "sorted globally by the key(s)" for typed columns
# Context: a timestamp key sorts by instant, across differing zone offsets.
def test_timestamp_key_sorts_by_instant(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("ts", "timestamp")])
    src = write_csv(tmp_path / "a.csv", [
        "ts",
        "2024-07-01T12:00:00+02:00",   # 10:00Z
        "2024-07-01T11:00:00Z",
        "2024-07-01T09:00:00-01:00",   # 10:00Z ... equal to the first
    ])
    rows = run_tool("--output", "-", "--key", "ts",
                    "--schema", schema, src).rows()[1:]
    assert [r[0] for r in rows] == [
        "2024-07-01T10:00:00Z",
        "2024-07-01T10:00:00Z",
        "2024-07-01T11:00:00Z",
    ]


# Phrase: "sorted globally by the key(s)" for typed columns
# Context: fractional seconds participate in timestamp ordering.
def test_timestamp_fractional_seconds_ordering(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("ts", "timestamp")])
    src = write_csv(tmp_path / "a.csv", [
        "ts",
        "2024-07-01T12:00:00.500000Z",
        "2024-07-01T12:00:00Z",
        "2024-07-01T12:00:00.250000Z",
    ])
    rows = run_tool("--output", "-", "--key", "ts",
                    "--schema", schema, src).rows()[1:]
    assert [r[0] for r in rows] == [
        "2024-07-01T12:00:00Z",
        "2024-07-01T12:00:00.250000Z",
        "2024-07-01T12:00:00.500000Z",
    ]


# Phrase: "sorted globally by the key(s)" for typed columns
# Context: a float key sorts numerically, including negatives.
def test_float_key_sorts_numerically(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["v", "10.5", "-2.25", "2.5"])
    rows = run_tool("--output", "-", "--key", "v", src).rows()[1:]
    assert [float(r[0]) for r in rows] == [-2.25, 2.5, 10.5]


# Phrase: "sorted globally by the key(s)" for typed columns
# Context: a string key sorts lexicographically by code point.
def test_string_key_sorts_lexicographically(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["s", "banana", "Apple", "apple"])
    rows = run_tool("--output", "-", "--key", "s", src).rows()[1:]
    assert [r[0] for r in rows] == ["Apple", "apple", "banana"]


# Phrase: "sorted globally by the key(s)" for typed columns
# Context: a bool key sorts false before true.
def test_bool_key_sorts_false_before_true(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("b", "bool"), ("n", "int")])
    src = write_csv(tmp_path / "a.csv", ["b,n", "true,1", "false,2"])
    rows = run_tool("--output", "-", "--key", "b",
                    "--schema", schema, src).rows()[1:]
    assert [r[1] for r in rows] == ["2", "1"]


# Phrase: "Tool must handle inputs exceeding --memory-limit-mb constraint"
# Context: correctness of the global order is preserved when spilling.
def test_sort_correct_when_spilling(tmp_path):
    rows_a = ["id"] + [str(i) for i in range(0, 4000, 2)]
    rows_b = ["id"] + [str(i) for i in range(1, 4000, 2)]
    a = write_csv(tmp_path / "a.csv", rows_a)
    b = write_csv(tmp_path / "b.csv", rows_b)
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "1", a, b)
    assert res.returncode == 0, res.stderr
    got = [int(v) for v in col(res.rows(), "id")]
    assert got == list(range(4000))


# Phrase: "Sort must be stable ..." combined with spilling
# Context: stability must survive the external merge.
def test_stability_survives_spilling(tmp_path):
    lines = ["k,seq"] + ["%d,%d" % (i % 7, i) for i in range(4000)]
    src = write_csv(tmp_path / "a.csv", lines)
    res = run_tool("--output", "-", "--key", "k",
                   "--memory-limit-mb", "1", src)
    assert res.returncode == 0, res.stderr
    rows = res.rows()[1:]
    for group in range(7):
        seqs = [int(r[1]) for r in rows if int(r[0]) == group]
        assert seqs == sorted(seqs)
