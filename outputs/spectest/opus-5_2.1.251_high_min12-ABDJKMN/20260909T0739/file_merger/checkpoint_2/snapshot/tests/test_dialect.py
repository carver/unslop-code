"""`Fixed CSV assumptions` and `Deterministic Dialect Details`."""
from conftest import merge, parse_csv, run, write, write_schema


# --- Spec: "Output delimiter `,`, quote `\"`; escape by doubling quotes;
#            `\n` line endings; header row first" -------------------------
def test_output_line_endings_are_lf(tmp_path):
    files = {"a.csv": "id\n9\n2\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert "\r" not in r.stdout
    assert r.stdout == "id\n2\n9\n"


def test_output_quotes_fields_containing_delimiter(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    files = {"a.csv": 'id,v\n1,"a,b"\n'}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.stdout == 'id,v\n1,"a,b"\n'


def test_output_escapes_quotes_by_doubling(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    files = {"a.csv": 'id,v\n1,"say ""hi"""\n'}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.stdout == 'id,v\n1,"say ""hi"""\n'
    assert r.rows()[1] == ["1", 'say "hi"']


# --- Spec: "Delimiter is comma (`,`)" on input ---------------------------
def test_input_delimiter_is_comma(tmp_path):
    files = {"a.csv": "a,b,c\n1,2,3\n"}
    r = merge(tmp_path, files, "--key", "a")
    assert r.ok, r
    assert r.rows()[0] == ["a", "b", "c"]


# --- Spec: "All inputs are UTF-8" ---------------------------------------
def test_utf8_roundtrip(tmp_path):
    files = {"a.csv": "id,v\n7,héllo ✓\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["7", "héllo ✓"]


# --- Spec: "with a header row" (first line names the columns) ------------
def test_header_row_is_not_data(tmp_path):
    files = {"a.csv": "id\n1\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert len(r.rows()) == 2


# --- Spec: "Quote character defaults to `\"`" ---------------------------
def test_default_quotechar_on_input(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    files = {"a.csv": 'id,v\n1,"quoted, value"\n'}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "quoted, value"]


# --- Spec: "Quote character ... overrideable via flags" -----------------
def test_custom_quotechar_on_input(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    files = {"a.csv": "id,v\n1,|quoted, value|\n"}
    r = merge(
        tmp_path, files, "--key", "id", "--schema", str(schema),
        "--csv-quotechar", "|",
    )
    assert r.ok, r
    # Checkpoint 2: "Use configured CSV dialect flags for output
    # quoting/escaping" - the writer now uses the configured quote character
    # too (see AMBIGUITIES T8).
    assert r.stdout == "id,v\n1,|quoted, value|\n"


# --- Spec: "escape character defaults to doubling the quote (`\"\"`),
#            overrideable via flags" -----------------------------------
def test_custom_escapechar_on_input(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "string")])
    files = {"a.csv": 'id,v\n1,"say \\"hi\\""\n'}
    r = merge(
        tmp_path, files, "--key", "id", "--schema", str(schema),
        "--csv-escapechar", "\\",
    )
    assert r.ok, r
    # Input unescapes to `say "hi"`; checkpoint 2 re-escapes it on output with
    # the same configured escape character (see AMBIGUITIES T8).
    assert r.stdout == 'id,v\n1,say \\"hi\\"\n'


# --- Spec: "`date` stays `YYYY-MM-DD`" ---------------------------------
def test_date_output_shape(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("d", "date")])
    files = {"a.csv": "d\n2024-07-01\n"}
    r = merge(tmp_path, files, "--key", "d", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["2024-07-01"]


# --- Spec: "`timestamp` normalized to UTC with `Z`
#            (e.g., `2024-07-01T12:00:00Z`)" ---------------------------
def test_timestamp_output_shape(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("t", "timestamp")])
    files = {"a.csv": "t\n2024-07-01T12:00:00+00:00\n"}
    r = merge(tmp_path, files, "--key", "t", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["2024-07-01T12:00:00Z"]


# --- Spec: "if source lacked zone, treat as UTC" ----------------------
def test_timestamp_space_separator_and_no_zone(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("t", "timestamp")])
    files = {"a.csv": "t\n2024-07-01 12:00:00\n"}
    r = merge(tmp_path, files, "--key", "t", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["2024-07-01T12:00:00Z"]


# --- Spec ambiguity T12: fractional seconds are preserved -------------
def test_timestamp_fractional_seconds(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("t", "timestamp")])
    files = {"a.csv": "t\n2024-07-01T12:00:00.500Z\n"}
    r = merge(tmp_path, files, "--key", "t", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["2024-07-01T12:00:00.5Z"]


# --- Spec ambiguity T19: a UTF-8 BOM on the header is not part of the name
def test_bom_is_stripped(tmp_path):
    p = write(tmp_path, "a.csv", "﻿id,v\n1,x\n")
    r = run("--output", "-", "--key", "id", p, cwd=tmp_path)
    assert r.ok, r
    assert r.rows()[0] == ["id", "v"]


# --- Spec ambiguity T19: degenerate inputs ---------------------------
def test_empty_file_contributes_nothing(tmp_path):
    files = {"a.csv": "", "b.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id"], ["7"]]


def test_short_and_long_rows_are_tolerated(tmp_path):
    files = {"a.csv": "a,b\n1\n2,x,extra\n"}
    r = merge(tmp_path, files, "--key", "a")
    assert r.ok, r
    assert r.rows() == [["a", "b"], ["1", ""], ["2", "x"]]


# --- Spec: "RFC-4180 compliant" - a blank line is not a record, but a quoted
#           empty field is (see AMBIGUITIES T19) ---------------------------
def test_blank_line_is_not_a_record(tmp_path):
    files = {"a.csv": "id,v\n7,x\n\n8,y\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "v"], ["7", "x"], ["8", "y"]]


def test_quoted_empty_field_is_a_record(tmp_path):
    files = {"a.csv": 'v\n""\nb\n'}
    r = merge(tmp_path, files, "--key", "v")
    assert r.ok, r
    assert r.rows() == [["v"], [""], ["b"]]
