"""Output shaping: destination, header, column order and null rendering."""

from conftest import rows_of


# Spec: "Single CSV with header row and all rows from inputs"
# Context: every data row of every input appears exactly once under one header.
def test_all_input_rows_appear_under_a_single_header(make_csv, run, workdir):
    make_csv("a.csv", "id,note\n1,a\n3,c\n")
    make_csv("b.csv", "id,note\n2,b\n")
    run("--output", "out.csv", "--key", "id", "a.csv", "b.csv")
    rows = rows_of((workdir / "out.csv").read_text())
    assert rows == [["id", "note"], ["1", "a"], ["2", "b"], ["3", "c"]]


# Spec: "If `--output -`: write to stdout"
def test_dash_output_writes_to_stdout(make_csv, run):
    make_csv("a.csv", "id\n7\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert proc.stdout == "id\n7\n"


# Spec: "otherwise write to file path"
def test_named_output_writes_to_that_path_and_not_stdout(make_csv, run, workdir):
    make_csv("a.csv", "id\n7\n")
    proc = run("--output", "out.csv", "--key", "id", "a.csv")
    assert proc.stdout == ""
    assert (workdir / "out.csv").read_text() == "id\n7\n"


# Spec: "Columns in output header must match the resolved schema order"
# Context: with a provided schema the order is the schema's, not the input's.
def test_header_follows_provided_schema_order(make_csv, make_schema, run):
    make_csv("a.csv", "note,id\nhi,1\n")
    make_schema("s.json", [("id", "int"), ("note", "string")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.csv")
    assert rows_of(proc.stdout) == [["id", "note"], ["1", "hi"]]


# Spec: "Missing values emitted as the null literal (default empty string)"
def test_missing_values_default_to_empty_string(make_csv, run):
    make_csv("a.csv", "id,note\n1,\n")
    make_csv("b.csv", "id\n2\n")
    proc = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert rows_of(proc.stdout) == [["id", "note"], ["1", ""], ["2", ""]]


# Spec: "Missing values emitted as the null literal ... (override with `--csv-null-literal`)"
def test_null_literal_override_is_used_for_missing_values(make_csv, run):
    make_csv("a.csv", "id,note\n1,\n")
    make_csv("b.csv", "id\n2\n")
    proc = run("--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.csv", "b.csv")
    assert rows_of(proc.stdout) == [["id", "note"], ["1", "NULL"], ["2", "NULL"]]


# Spec: "all rows from inputs" - a header-only input contributes no rows.
def test_header_only_input_contributes_no_rows(make_csv, run):
    make_csv("a.csv", "id\n7\n")
    make_csv("b.csv", "id\n")
    proc = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert rows_of(proc.stdout) == [["id"], ["7"]]
