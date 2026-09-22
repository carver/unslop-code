"""Spec section: Schema Resolution & Column Order (the inference branch).

The inferred type is observed through its side effects: canonical rendering of
the cast value, and numeric vs lexicographic ordering when it is the sort key.
"""
from conftest import column, table


# Phrase: "If --schema not provided: infer schema from union of all input headers"
# Context: the output header is the union, not the first file's header.
def test_header_is_the_union_of_input_headers(run, csv_file):
    csv_file("a.csv", "id,a\n1,x\n")
    csv_file("b.csv", "id,b\n2,y\n")
    assert table(run("--output", "-", "--key", "id", "a.csv", "b.csv").stdout)[0] == [
        "a", "b", "id",
    ]


# Phrase: "Column order: ascending lexicographic order of column names"
# Context: T17 — codepoint ordering, so uppercase sorts before lowercase.
def test_inferred_columns_are_lexicographic(run, csv_file):
    csv_file("a.csv", "zebra,Apple,mango,_x\n1,2,3,4\n")
    assert table(run("--output", "-", "--key", "zebra", "a.csv").stdout)[0] == [
        "Apple", "_x", "mango", "zebra",
    ]


# Phrase: "Missing columns in a file filled with null literal"
# Context: inference branch counterpart of the schema branch rule.
def test_missing_columns_are_null_under_inference(run, csv_file):
    csv_file("a.csv", "id,a\n1,x\n")
    csv_file("b.csv", "id,b\n2,y\n")
    res = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert table(res.stdout)[1:] == [["x", "", "1"], ["", "y", "2"]]


# Phrase: "strict (default): infer types based on observed values"
# Context: a column of integers infers as int, so it sorts numerically and
#   renders canonically.
def test_strict_infers_int(run, csv_file):
    csv_file("a.csv", "id\n10\n9\n007\n")
    assert column(run("--output", "-", "--key", "id", "a.csv").stdout, "id") == [
        "7", "9", "10",
    ]


# Phrase: "strict (default)"
# Context: the default mode is strict when --infer is omitted.
def test_strict_is_the_default(run, csv_file):
    csv_file("a.csv", "id\n1\n")
    csv_file("b.csv", "id\nx\n")
    default = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    explicit = run("--output", "-", "--key", "id", "--infer", "strict", "a.csv", "b.csv")
    assert default.stdout == explicit.stdout


# Phrase: "columns with conflicting types across files fall back to `string`"
# Context: int in one file, text in another.
def test_strict_conflicting_types_fall_back_to_string(run, csv_file):
    csv_file("a.csv", "id\n10\n")
    csv_file("b.csv", "id\nabc\n")
    res = run("--output", "-", "--key", "id", "--infer", "strict", "a.csv", "b.csv")
    assert column(res.stdout, "id") == ["10", "abc"]


# Phrase: "columns with conflicting types across files fall back to string"
# Context: int and float are different types, so they conflict under strict.
def test_strict_int_and_float_conflict(run, csv_file):
    csv_file("a.csv", "n,k\n2,1\n")
    csv_file("b.csv", "n,k\n1.50,2\n")
    res = run("--output", "-", "--key", "k", "--infer", "strict", "a.csv", "b.csv")
    assert column(res.stdout, "n") == ["2", "1.50"]


# Phrase: "infer types based on observed values"
# Context: a column with one type in a single file is not a conflict.
def test_strict_agreeing_files_keep_the_type(run, csv_file):
    csv_file("b.csv", "n\n1.5\n")
    csv_file("c.csv", "n\n3.25\n")
    res = run("--output", "-", "--key", "n", "--infer", "strict", "b.csv", "c.csv")
    assert column(res.stdout, "n") == ["1.5", "3.25"]


# Phrase: "strict ... columns with conflicting types across files"
# Context: T3 — under strict an empty cell is an observed value, so it forces string.
def test_strict_blank_cell_forces_string(run, csv_file):
    csv_file("a.csv", "id,n\n1,10\n2,\n3,9\n")
    res = run("--output", "-", "--key", "n", "--infer", "strict", "a.csv")
    assert column(res.stdout, "n") == ["", "10", "9"]


# Phrase: "loose: ... empty strings are treated as nulls and don't affect inference"
# Context: same data as above, but loose keeps the int type.
def test_loose_ignores_blank_cells(run, csv_file):
    csv_file("a.csv", "id,n\n1,10\n2,\n3,9\n")
    res = run("--output", "-", "--key", "n", "--infer", "loose", "a.csv")
    assert column(res.stdout, "n") == ["", "9", "10"]


# Phrase: "loose: prefer numeric/temporal types if all non-null observed values parse"
# Context: values pooled across files rather than compared per file.
def test_loose_pools_values_across_files(run, csv_file):
    csv_file("a.csv", "n\n2\n")
    csv_file("b.csv", "n\n1.50\n")
    res = run("--output", "-", "--key", "n", "--infer", "loose", "a.csv", "b.csv")
    assert column(res.stdout, "n") == ["1.5", "2.0"]


# Phrase: "loose: ... otherwise fall back to `string`"
# Context: one unparseable value drags the whole column to string.
def test_loose_falls_back_to_string(run, csv_file):
    csv_file("a.csv", "n\n2\n")
    csv_file("b.csv", "n\nabc\n")
    res = run("--output", "-", "--key", "n", "--infer", "loose", "a.csv", "b.csv")
    assert column(res.stdout, "n") == ["2", "abc"]


# Phrase: "Type priority: timestamp > date > bool > int > float > string"
# Context: T1 — 1/0 parse as both bool and int, and bool outranks int.
def test_priority_prefers_bool_over_int(run, csv_file):
    csv_file("a.csv", "id,flag\n1,1\n2,0\n")
    res = run("--output", "-", "--key", "id", "--infer", "loose", "a.csv")
    assert column(res.stdout, "flag") == ["true", "false"]


# Phrase: "Type priority: ... int > float"
# Context: whole numbers parse as both; int wins and renders without a decimal.
def test_priority_prefers_int_over_float(run, csv_file):
    csv_file("a.csv", "n\n2\n3\n")
    assert column(run("--output", "-", "--key", "n", "a.csv").stdout, "n") == ["2", "3"]


# Phrase: "Type priority: timestamp > date"
# Context: T2 — pure YYYY-MM-DD columns infer as date and stay unnormalized.
def test_date_only_column_infers_as_date(run, csv_file):
    csv_file("a.csv", "d\n2024-07-02\n2024-01-05\n")
    assert column(run("--output", "-", "--key", "d", "a.csv").stdout, "d") == [
        "2024-01-05", "2024-07-02",
    ]


# Phrase: "Type priority: timestamp > date"
# Context: T2 — once any value carries a time part, timestamp wins for the column.
def test_mixed_date_and_timestamp_infers_as_timestamp(run, csv_file):
    csv_file("a.csv", "t\n2024-07-01T06:00:00Z\n2024-07-01\n")
    res = run("--output", "-", "--key", "t", "--infer", "loose", "a.csv")
    assert column(res.stdout, "t") == [
        "2024-07-01T00:00:00Z", "2024-07-01T06:00:00Z",
    ]


# Phrase: "infer schema from union of all input headers"
# Context: T14 — a column with no observed value falls back to string.
def test_all_null_column_infers_as_string(run, csv_file):
    csv_file("a.csv", "id,empty\n1,\n2,\n")
    res = run("--output", "-", "--key", "id", "--infer", "loose", "a.csv")
    assert column(res.stdout, "empty") == ["", ""]


# Phrase: "infer types based on observed values"
# Context: bools spelled as words, in either case.
def test_bool_words_infer_as_bool(run, csv_file):
    csv_file("a.csv", "id,b\n1,TRUE\n2,False\n")
    res = run("--output", "-", "--key", "id", "a.csv")
    assert column(res.stdout, "b") == ["true", "false"]
