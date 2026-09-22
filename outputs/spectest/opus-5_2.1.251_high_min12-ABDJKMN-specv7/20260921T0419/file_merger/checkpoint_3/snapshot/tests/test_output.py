"""Spec section: Output."""
from conftest import body, header


# Phrase: "Single CSV with header row and all rows from inputs"
# Context: Output; no rows dropped, no de-duplication.
def test_all_rows_from_all_inputs_present(run, work):
    work.csv("a.csv", ["id"], [["1"], ["3"]])
    work.csv("b.csv", ["id"], [["2"], ["3"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"), work.path("b.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["2"], ["3"], ["3"]]


def test_duplicate_rows_are_not_deduplicated(run, work):
    work.csv("a.csv", ["id", "v"], [["5", "x"], ["5", "x"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["5", "x"], ["5", "x"]]


# Phrase: "sorted globally by the key(s)"
# Context: Output; ordering spans file boundaries.
def test_sort_is_global_across_files(run, work):
    work.csv("a.csv", ["id"], [["1"], ["5"]])
    work.csv("b.csv", ["id"], [["2"], ["4"]])
    work.csv("c.csv", ["id"], [["3"]])
    r = run(
        "--output", "-", "--key", "id",
        work.path("a.csv"), work.path("b.csv"), work.path("c.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["2"], ["3"], ["4"], ["5"]]


# Phrase: "Columns in output header must match the resolved schema order"
# Context: Output.
def test_header_matches_schema_order(run, work):
    work.schema("s.json", [("z", "string"), ("a", "int")])
    work.csv("a.csv", ["a", "z"], [["1", "x"]])
    r = run(
        "--output", "-", "--key", "a", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["z", "a"]
    assert body(r) == [["x", "1"]]


def test_header_matches_inferred_order(run, work):
    work.csv("a.csv", ["b", "a"], [["1", "2"]])
    work.csv("b.csv", ["c"], [["3"]])
    r = run("--output", "-", "--key", "a", work.path("a.csv"), work.path("b.csv"))
    assert r.ok, r.stderr
    assert header(r) == ["a", "b", "c"]


# Phrase: "Missing values emitted as the null literal (default empty string...)"
# Context: Output.
def test_missing_values_default_to_empty_string(run, work):
    work.csv("a.csv", ["id", "v"], [["1", ""]])
    work.csv("b.csv", ["id"], [["2"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"), work.path("b.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["1", ""], ["2", ""]]


# Phrase: "(...override with `--csv-null-literal`)"
# Context: Output.
def test_null_literal_override(run, work):
    work.csv("a.csv", ["id", "v"], [["1", ""]])
    work.csv("b.csv", ["id"], [["2"]])
    r = run(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL",
        work.path("a.csv"), work.path("b.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "NULL"], ["2", "NULL"]]


# Phrase: "Missing input columns filled with null literal" (schema path)
# Context: Schema Resolution; combined with --csv-null-literal.
def test_null_literal_used_for_schema_missing_columns(run, work):
    work.schema("s.json", [("id", "int"), ("extra", "string")])
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--csv-null-literal", "NA", work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "NA"]]


# Phrase: "header row and all rows from inputs"
# Context: Output; header-only inputs contribute no rows.
def test_header_only_input_produces_header_only_output(run, work):
    work.write("a.csv", "id,v\n")
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert r.stdout == "id,v\n"
