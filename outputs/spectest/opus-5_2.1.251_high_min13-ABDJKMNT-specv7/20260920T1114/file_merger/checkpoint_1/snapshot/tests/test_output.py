"""Spec section: Output — destination, header, column order, null literal."""

from conftest import header_of, parse_csv, rows_of


# Phrase: "Single CSV with header row and all rows from inputs"
# Context: Output. Every input row appears exactly once.
def test_all_input_rows_are_emitted(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n1\n3\n")
    csv_file("b.csv", "id\n2\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert rows_of(result.stdout) == [["1"], ["1"], ["2"], ["3"]]


# Phrase: "If --output -: write to stdout"
# Context: Output.
def test_dash_output_goes_to_stdout(csv_file, run_tool):
    csv_file("a.csv", "id\n7\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.stdout == "id\n7\n"


# Phrase: "otherwise write to file path"
# Context: Output.
def test_named_output_is_written_to_the_file(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n2\n1\n")
    result = run_tool("--output", "merged.csv", "--key", "id", "a.csv")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (workdir / "merged.csv").read_text(encoding="utf-8") == "id\n1\n2\n"


# Phrase: "Columns in output header must match the resolved schema order"
# Context: Output, with an explicit schema.
def test_output_header_follows_schema_order(csv_file, run_tool):
    csv_file("a.csv", "note,id\nhello,1\n")
    csv_file(
        "schema.json",
        '{"columns": [{"name": "id", "type": "int"}, {"name": "note", "type": "string"}]}',
    )
    result = run_tool("--output", "-", "--key", "id", "--schema", "schema.json", "a.csv")
    assert header_of(result.stdout) == ["id", "note"]
    assert rows_of(result.stdout) == [["1", "hello"]]


# Phrase: "Missing values emitted as the null literal (default empty string)"
# Context: Output. A column absent from a file is null for that file's rows.
def test_missing_values_default_to_empty_string(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,a\n")
    csv_file("b.csv", "id\n2\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert rows_of(result.stdout) == [["1", "a"], ["2", ""]]


# Phrase: "override with --csv-null-literal"
# Context: Output.
def test_null_literal_override_is_used_for_missing_values(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,a\n")
    csv_file("b.csv", "id\n2\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.csv", "b.csv"
    )
    assert rows_of(result.stdout) == [["1", "a"], ["2", "NULL"]]


# Phrase: "Missing values emitted as the null literal"
# Context: Output. An empty cell inside a file is a missing value too.
def test_empty_cell_is_emitted_as_the_null_literal(csv_file, run_tool):
    csv_file("a.csv", "id,note\n7,\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.csv"
    )
    assert rows_of(result.stdout) == [["7", "NULL"]]


# Phrase: "Missing values emitted as the null literal ... override with --csv-null-literal"
# Context: Output. Ambiguity T9: the literal is also recognised on input.
def test_null_literal_is_recognised_in_input_cells(csv_file, run_tool):
    csv_file("a.csv", "id,amount\n1,NULL\n")
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}, {"name": "amount", "type": "float"}]}')
    result = run_tool(
        "--output", "-", "--key", "id",
        "--schema", "schema.json",
        "--csv-null-literal", "NULL",
        "--on-type-error", "fail",
        "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1", "NULL"]]


# Phrase: "Single CSV with header row"
# Context: Output. The header is emitted even when there are no data rows.
def test_header_is_emitted_for_empty_result(csv_file, run_tool):
    csv_file("a.csv", "id,note\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.stdout == "id,note\n"


# Phrase: "produces one sorted CSV output"
# Context: Output. Duplicate header names across inputs collapse into one column.
def test_shared_columns_collapse_into_one(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,a\n")
    csv_file("b.csv", "note,id\nb,2\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert header_of(result.stdout) == ["id", "note"]
    assert rows_of(result.stdout) == [["1", "a"], ["2", "b"]]


# Phrase: "Single CSV with header row and all rows from inputs"
# Context: Output. Nothing but the CSV is written to stdout.
def test_stdout_contains_only_the_csv(csv_file, run_tool):
    csv_file("a.csv", "id\n7\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert parse_csv(result.stdout) == [["id"], ["7"]]
