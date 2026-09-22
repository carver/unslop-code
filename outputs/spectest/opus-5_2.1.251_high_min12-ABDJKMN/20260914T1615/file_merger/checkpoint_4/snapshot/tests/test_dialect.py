"""Spec section: Fixed CSV assumptions + Deterministic Dialect Details."""

import csv
import io

from conftest import body, col, header, lines, read_text, run_ok, write, write_schema


# --- Spec: "Delimiter is comma (`,`)" on input ---
# Context: Fixed CSV assumptions.
def test_input_delimiter_is_comma(ws):
    a = write(ws / "a.csv", "k,v\n5,x\n")
    res = run_ok("--output", "-", "--key", "k", a)
    assert header(res.stdout) == ["k", "v"]


# --- Spec: "Output delimiter `,`" ---
# Context: Deterministic Dialect Details.
def test_output_delimiter_is_comma(ws):
    a = write(ws / "a.csv", "k,v\n5,x\n")
    res = run_ok("--output", "-", "--key", "k", a)
    assert "5,x" in res.stdout


# --- Spec: "line ending `\n`" / "`\n` line endings" ---
# Context: Fixed CSV assumptions + Deterministic Dialect Details.
def test_output_line_endings_are_lf(ws):
    a = write(ws / "a.csv", "k,v\n2,x\n1,y\n")
    out = ws / "o.csv"
    run_ok("--output", str(out), "--key", "k", a)
    with open(out, "rb") as fh:
        raw = fh.read()
    assert b"\r" not in raw
    assert raw == b"k,v\n1,y\n2,x\n"


# --- Spec: "header row first" ---
# Context: Deterministic Dialect Details.
def test_header_row_first(ws):
    a = write(ws / "a.csv", "k,v\n5,x\n")
    res = run_ok("--output", "-", "--key", "k", a)
    assert lines(res.stdout)[0] == "k,v"


# --- Spec: "RFC-4180 compliant" input with quoted fields ---
# Context: Fixed CSV assumptions; a quoted field may contain the delimiter.
def test_quoted_field_containing_comma(ws):
    a = write(ws / "a.csv", 'k,v\n5,"a,b"\n')
    res = run_ok("--output", "-", "--key", "k", a)
    assert col(res.stdout, "v") == ["a,b"]
    assert '"a,b"' in res.stdout


# --- Spec: "escape character defaults to doubling the quote (`\"\"`)" on input ---
# Context: Fixed CSV assumptions.
def test_doubled_quote_input_is_unescaped(ws):
    a = write(ws / "a.csv", 'k,v\n5,"say ""hi"""\n')
    res = run_ok("--output", "-", "--key", "k", a)
    assert col(res.stdout, "v") == ['say "hi"']


# --- Spec: "escape by doubling quotes" on output ---
# Context: Deterministic Dialect Details.
def test_output_escapes_by_doubling_quotes(ws):
    a = write(ws / "a.csv", 'k,v\n5,"say ""hi"""\n')
    res = run_ok("--output", "-", "--key", "k", a)
    assert lines(res.stdout)[1] == '5,"say ""hi"""'


# --- Spec: "Quote character defaults to `\"`" on output ---
# Context: Deterministic Dialect Details; fields needing quoting use `"`.
def test_output_quotes_with_double_quote_by_default(ws):
    a = write(ws / "a.csv", 'k,v\n5,"a,b"\n')
    res = run_ok("--output", "-", "--key", "k", a)
    assert lines(res.stdout)[1] == '5,"a,b"'


# --- Spec: "Quote character ... overrideable via flags" (--csv-quotechar) ---
# Context: Fixed CSV assumptions; input parsed with the given quote character.
def test_csv_quotechar_applies_to_input(ws):
    a = write(ws / "a.csv", "k,v\n5,'a,b'\n")
    res = run_ok("--output", "-", "--key", "k", "--csv-quotechar", "'", a)
    assert col(res.stdout, "v", quotechar="'") == ["a,b"]


# --- Spec: "--csv-quotechar <CHAR>" also shapes the emitted dialect ---
# Context: Usage + Deterministic Dialect Details; see AMBIGUITIES T10.
def test_csv_quotechar_applies_to_output(ws):
    a = write(ws / "a.csv", "k,v\n5,'a,b'\n")
    res = run_ok("--output", "-", "--key", "k", "--csv-quotechar", "'", a)
    assert lines(res.stdout)[1] == "5,'a,b'"


# --- Spec: "escape character ... overrideable via flags" (--csv-escapechar) ---
# Context: Fixed CSV assumptions; input escape character.
def test_csv_escapechar_applies_to_input(ws):
    a = write(ws / "a.csv", 'k,v\n5,"say \\"hi\\""\n')
    res = run_ok("--output", "-", "--key", "k", "--csv-escapechar", "\\", a)
    assert col(res.stdout, "v") == ['say "hi"']


# --- Spec: "escape by doubling quotes" on output regardless of input escaping ---
# Context: Deterministic Dialect Details; see AMBIGUITIES T10.
def test_output_still_doubles_when_escapechar_given(ws):
    a = write(ws / "a.csv", 'k,v\n5,"say \\"hi\\""\n')
    res = run_ok("--output", "-", "--key", "k", "--csv-escapechar", "\\", a)
    assert lines(res.stdout)[1] == '5,"say ""hi"""'


# --- Spec: "All inputs are UTF-8 ... with a header row" ---
# Context: Fixed CSV assumptions; the first line names columns, it is not data.
def test_header_row_is_not_data(ws):
    a = write(ws / "a.csv", "k\n5\n")
    res = run_ok("--output", "-", "--key", "k", a)
    assert body(res.stdout) == ["5"]


# --- Spec: output is parseable by a standard RFC-4180 reader ---
# Context: Deterministic Dialect Details.
def test_output_round_trips_through_csv_reader(ws):
    a = write(ws / "a.csv", 'k,v\n2,"multi, part"\n1,"q""uote"\n')
    res = run_ok("--output", "-", "--key", "k", a)
    rows = list(csv.reader(io.StringIO(res.stdout)))
    assert rows == [["k", "v"], ["1", 'q"uote'], ["2", "multi, part"]]


# --- Spec: header names are emitted verbatim (quoted when needed) ---
# Context: Deterministic Dialect Details; column names may contain a comma.
def test_header_names_quoted_when_needed(ws):
    a = write(ws / "a.csv", 'k,"we,ird"\n5,x\n')
    res = run_ok("--output", "-", "--key", "k", a)
    assert lines(res.stdout)[0] == 'k,"we,ird"'


# --- Spec: "All inputs are UTF-8" — BOM-free UTF-8 text passes through ---
# Context: Fixed CSV assumptions.
def test_non_ascii_values_preserved(ws):
    a = write(ws / "a.csv", "k,v\n1,naïve\n2,日本\n")
    res = run_ok("--output", "-", "--key", "k", a)
    assert col(res.stdout, "v") == ["naïve", "日本"]


# --- Spec: "Missing values emitted as the null literal" — literal is quoted if needed ---
# Context: Output + Deterministic Dialect Details.
def test_null_literal_quoted_when_needed(ws):
    a = write(ws / "a.csv", "k,v\n5,\n")
    res = run_ok("--output", "-", "--key", "k", "--csv-null-literal", "a,b", a)
    assert lines(res.stdout)[1] == '5,"a,b"'
