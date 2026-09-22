"""Behaviour locked in by the choices recorded in AMBIGUITIES.md.

Each test names the ambiguity entry it pins down.
"""
from conftest import run_tool, write_csv, write_schema, col


# T1 - RESOLVED by checkpoint 2: "Use configured CSV dialect flags for output
# quoting/escaping", so --csv-quotechar now applies to the writer as well.
# Escaping stays doubling-based (T29).
def test_output_quotechar_follows_the_flag(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["k,v", "7,'a,b'"])
    res = run_tool("--output", "-", "--key", "k",
                   "--csv-quotechar", "'", src)
    assert res.stdout.splitlines()[1] == "7,'a,b'"


def test_output_quoting_doubles_the_quotechar(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["k,v", "7,'it''s,here'"])
    res = run_tool("--output", "-", "--key", "k",
                   "--csv-quotechar", "'", src)
    assert res.stdout.splitlines()[1] == "7,'it''s,here'"


# T2 - a backslash not introducing an escape is preserved verbatim.
# Spec: "escape character defaults to doubling the quote and accepts
# backslash-escapes"
def test_lone_backslash_preserved(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['k,v', '7,"C:\\path"'])
    res = run_tool("--output", "-", "--key", "k", src)
    assert res.rows()[1] == ["7", "C:\\path"]


# T3 - strict counts empty cells as observed values, so they force string.
# Spec: "strict: infer types based on observed values"
def test_strict_empty_cell_forces_string(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["v", "10", "", "9"])
    res = run_tool("--output", "-", "--key", "v", "--infer", "strict", src)
    # string ordering (null first, then "10" < "9")
    assert col(res.rows(), "v") == ["", "10", "9"]


# T3 - loose is global across files, so it does not "conflict" the way strict
# does.
# Spec: "loose: prefer numeric/temporal types if all non-null observed values
# parse"
def test_loose_is_global_across_files(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["v", "10"])
    b = write_csv(tmp_path / "b.csv", ["v", "9.5"])
    res = run_tool("--output", "-", "--key", "v", "--infer", "loose", a, b)
    assert col(res.rows(), "v") == ["9.5", "10.0"]


# T4 - inference picks the highest priority type that every cell admits.
# Spec: "Type priority: timestamp > date > bool > int > float > string"
def test_priority_highest_common_type(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["v,i", "1,1", "2,2"])
    res = run_tool("--output", "-", "--key", "i", "--infer", "loose", src)
    # 2 is not a bool, so the common type drops to int
    assert col(res.rows(), "v") == ["1", "2"]


# T5 - a date-only column infers as date, not timestamp.
# Spec: "date stays YYYY-MM-DD"
def test_date_only_column_infers_as_date(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["d", "2024-07-01", "2024-01-05"])
    res = run_tool("--output", "-", "--key", "d", "--infer", "loose", src)
    assert col(res.rows(), "d") == ["2024-01-05", "2024-07-01"]


# T5 - an explicit timestamp schema still accepts a bare date as midnight UTC.
# Spec: "Cast every input cell into target type"
def test_bare_date_casts_to_midnight_utc(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("ts", "timestamp")])
    src = write_csv(tmp_path / "a.csv", ["ts", "2024-07-01"])
    res = run_tool("--output", "-", "--key", "ts", "--schema", schema, src)
    assert col(res.rows(), "ts") == ["2024-07-01T00:00:00Z"]


# T6 - bool renders lowercase.
# Spec: "bool includes 1/0 along with standard values"
def test_bool_renders_lowercase(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("b", "bool"), ("i", "int")])
    src = write_csv(tmp_path / "a.csv", ["b,i", "TRUE,1", "0,2"])
    res = run_tool("--output", "-", "--key", "i", "--schema", schema, src)
    assert col(res.rows(), "b") == ["true", "false"]


# T7 - successful casts are re-rendered canonically.
# Spec: "Cast every input cell into target type"
def test_int_rendered_canonically(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("n", "int")])
    src = write_csv(tmp_path / "a.csv", ["n", "007", "+3"])
    res = run_tool("--output", "-", "--key", "n", "--schema", schema, src)
    assert col(res.rows(), "n") == ["3", "7"]


# T8 - the null literal is also recognised when reading input.
# Spec: "Missing values emitted as the null literal ... override with
# --csv-null-literal"
def test_null_literal_recognised_on_input(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["k,v", "1,NULL", "2,x"])
    res = run_tool("--output", "-", "--key", "v",
                   "--csv-null-literal", "NULL", src)
    rows = res.rows()[1:]
    assert rows[0] == ["1", "NULL"]   # read as null, emitted as the literal


# T8 - an empty string cell is a null for a string column too.
# Spec: "empty strings are treated as nulls"
def test_empty_string_cell_is_null_for_string_column(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("s", "string"), ("i", "int")])
    src = write_csv(tmp_path / "a.csv", ["s,i", ",1"])
    res = run_tool("--output", "-", "--key", "i", "--schema", schema,
                   "--csv-null-literal", "NA", src)
    assert col(res.rows(), "s") == ["NA"]


# T11 - kept strings sort after the properly typed values of the column.
# Spec: "keep-string: emit original text as string"
def test_keep_string_sorts_after_typed_values(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("n", "int")])
    src = write_csv(tmp_path / "a.csv", ["n", "oops", "5", "1"])
    res = run_tool("--output", "-", "--key", "n", "--schema", schema,
                   "--on-type-error", "keep-string", src)
    assert col(res.rows(), "n") == ["1", "5", "oops"]


# T13 - surplus fields beyond the header are ignored.
# Spec: "Extra input columns not in schema are ignored"
def test_long_row_surplus_fields_ignored(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "7,x,surplus"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.rows() == [["id", "name"], ["7", "x"]]


# T14 - a blank body line in a one column file is a null row.
# Spec: "Missing values emitted as the null literal"
def test_blank_line_is_a_null_row(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["v", "b", "", "a"])
    res = run_tool("--output", "-", "--key", "v", src)
    assert col(res.rows(), "v") == ["", "a", "b"]


# T15 - only true/false/1/0 are booleans; other words are not.
# Spec: "bool includes 1/0 along with standard values"
def test_yes_no_is_not_bool(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["v,i", "yes,1", "no,2"])
    res = run_tool("--output", "-", "--key", "i", "--infer", "loose", src)
    assert col(res.rows(), "v") == ["yes", "no"]


# T16 - --key may be repeated.
# Spec: "--key <col>[,<col>...]"
def test_key_flag_may_repeat(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["g,n", "b,1", "a,2", "a,1"])
    res = run_tool("--output", "-", "--key", "g", "--key", "n", src)
    assert res.rows()[1:] == [["a", "1"], ["a", "2"], ["b", "1"]]


# T17 - nan/inf are not floats.
# Spec: "int, float, string: standard parsing"
def test_nan_is_not_a_float(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("n", "float"), ("i", "int")])
    src = write_csv(tmp_path / "a.csv", ["n,i", "nan,1", "1.5,2"])
    res = run_tool("--output", "-", "--key", "i", "--schema", schema, src)
    assert col(res.rows(), "n") == ["", "1.5"]


# Schema supersedes --infer entirely.
# Spec: "If --schema is provided: JSON file with exact output schema"
def test_schema_overrides_infer_flag(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("v", "string")])
    src = write_csv(tmp_path / "a.csv", ["v", "10", "9"])
    for mode in ("strict", "loose"):
        res = run_tool("--output", "-", "--key", "v", "--schema", schema,
                       "--infer", mode, src)
        assert col(res.rows(), "v") == ["10", "9"]


# A missing input file is an error.
# Spec: "<INPUT1.csv> [<INPUT2.csv> ...]"
def test_missing_input_file_is_an_error(tmp_path):
    res = run_tool("--output", "-", "--key", "id", tmp_path / "nope.csv")
    assert res.returncode != 0
    assert res.stderr.strip() != ""
