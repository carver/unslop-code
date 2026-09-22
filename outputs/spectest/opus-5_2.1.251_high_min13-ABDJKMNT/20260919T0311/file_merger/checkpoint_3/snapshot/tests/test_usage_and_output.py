"""Spec section: Deliverables / Usage / Output."""
from conftest import column, lines, table


# Phrase: "Write `merge_files.py` with the following interface."
# Context: the deliverable is a single command-line script.
def test_tool_script_exists_and_runs():
    from conftest import TOOL

    assert TOOL.is_file()


# Phrase: "python merge_files.py --output <PATH|-> --key <col>[,<col>...] <INPUT1.csv> [<INPUT2.csv> ...]"
# Context: --output and --key are required; one or more positional inputs follow.
def test_missing_required_arguments_is_a_usage_error(run, csv_file):
    csv_file("a.csv", "id\n1\n")
    assert run("a.csv").returncode != 0
    assert run("--output", "-", "a.csv").returncode != 0
    assert run("--output", "-", "--key", "id").returncode != 0


# Phrase: "A command-line tool that ingests multiple CSVs, aligns their schemas,
#   and produces one sorted CSV output."
# Context: the end-to-end happy path over several files.
def test_merges_multiple_files_into_one_sorted_output(run, csv_file):
    csv_file("a.csv", "id,name\n3,c\n1,a\n")
    csv_file("b.csv", "id,name\n2,b\n")
    res = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert res.returncode == 0, res.stderr
    assert table(res.stdout) == [["id", "name"], ["1", "a"], ["2", "b"], ["3", "c"]]


# Phrase: "Single CSV with header row and all rows from inputs"
# Context: nothing is dropped or deduplicated when merging.
def test_every_input_row_is_present_exactly_once(run, csv_file):
    csv_file("a.csv", "id\n1\n1\n2\n")
    csv_file("b.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert column(res.stdout, "id") == ["1", "1", "1", "2"]


# Phrase: "If `--output -`: write to stdout; otherwise write to file path"
# Context: the two output destinations produce the same bytes.
def test_output_to_file_matches_output_to_stdout(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n2,x\n1,y\n")
    to_stdout = run("--output", "-", "--key", "id", "a.csv")
    to_file = run("--output", "merged.csv", "--key", "id", "a.csv")
    assert to_file.returncode == 0, to_file.stderr
    assert to_file.stdout == ""
    assert (tmp_path / "merged.csv").read_text(encoding="utf-8") == to_stdout.stdout


# Phrase: "Columns in output header must match the resolved schema order"
# Context: with an explicit schema the header is the schema's column order,
#   not the input header order.
def test_header_follows_schema_order(run, csv_file, schema_file):
    csv_file("a.csv", "name,id\nx,1\n")
    schema = schema_file([("id", "int"), ("name", "string")])
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.csv")
    assert table(res.stdout)[0] == ["id", "name"]


# Phrase: "Missing values emitted as the null literal (default empty string)"
# Context: a column absent from a file is null for that file's rows.
def test_missing_values_default_to_empty_string(run, csv_file):
    csv_file("a.csv", "id,extra\n1,here\n")
    csv_file("b.csv", "id\n2\n")
    res = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert table(res.stdout) == [["extra", "id"], ["here", "1"], ["", "2"]]


# Phrase: "override with `--csv-null-literal`"
# Context: the literal replaces the empty string for every emitted null.
def test_null_literal_override(run, csv_file):
    csv_file("a.csv", "id,extra\n1,here\n")
    csv_file("b.csv", "id\n2\n")
    res = run(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.csv", "b.csv"
    )
    assert table(res.stdout)[2] == ["NULL", "2"]


# Phrase: "Missing values emitted as the null literal"
# Context: T6 — an input cell equal to the null literal is read back as null,
#   so the tool round-trips its own output.
def test_null_literal_is_recognised_on_input(run, csv_file, schema_file):
    csv_file("a.csv", "id,amount\n1,NULL\n")
    schema = schema_file([("id", "int"), ("amount", "float")])
    res = run(
        "--output", "-", "--key", "id",
        "--schema", schema, "--csv-null-literal", "NULL",
        "--on-type-error", "fail", "a.csv",
    )
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "amount") == ["NULL"]


# Phrase: "with a **header row**"
# Context: a file with only a header contributes no rows.
def test_header_only_input_contributes_no_rows(run, csv_file):
    csv_file("a.csv", "id,v\n")
    csv_file("b.csv", "id,v\n7,x\n")
    res = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert table(res.stdout) == [["id", "v"], ["7", "x"]]


# Phrase: "Single CSV with header row"
# Context: the header is emitted even when no data rows exist at all.
def test_header_is_emitted_with_zero_rows(run, csv_file):
    csv_file("a.csv", "id,v\n")
    res = run("--output", "-", "--key", "id", "a.csv")
    assert res.returncode == 0, res.stderr
    assert lines(res.stdout) == ["id,v"]


# Phrase: "All inputs are UTF-8"
# Context: non-ASCII text survives the round trip.
def test_utf8_round_trip(run, csv_file):
    csv_file("a.csv", "id,name\n1,café ☕\n")
    res = run("--output", "-", "--key", "id", "a.csv")
    assert column(res.stdout, "name") == ["café ☕"]
