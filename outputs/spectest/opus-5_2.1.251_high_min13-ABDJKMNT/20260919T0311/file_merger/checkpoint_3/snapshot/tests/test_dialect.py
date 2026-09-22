"""Spec section: Fixed CSV assumptions and Deterministic Dialect Details."""
from conftest import column, lines, table


# Phrase: "Delimiter is comma (,); line ending \n"
# Context: output rows are separated by bare newlines, never CRLF.
def test_output_uses_lf_line_endings(run, csv_file, tmp_path):
    csv_file("a.csv", "id,v\n1,x\n2,y\n")
    run("--output", "merged.csv", "--key", "id", "a.csv")
    raw = (tmp_path / "merged.csv").read_bytes()
    assert b"\r" not in raw
    assert raw == b"id,v\n1,x\n2,y\n"


# Phrase: "Quote character defaults to \"; escape character defaults to doubling the quote"
# Context: default input parsing of quoted fields containing delimiters and quotes.
def test_default_quoting_on_input(run, csv_file):
    csv_file("a.csv", 'id,v\n1,"a,b"\n2,"say ""hi"""\n')
    res = run("--output", "-", "--key", "id", "a.csv")
    assert column(res.stdout, "v") == ["a,b", 'say "hi"']


# Phrase: "Output delimiter ,, quote \"; escape by doubling quotes"
# Context: fields needing protection are quoted on output, with doubled quotes.
def test_output_quotes_minimally_and_doubles(run, csv_file):
    csv_file("a.csv", 'id,v\n1,"a,b"\n2,"say ""hi"""\n3,plain\n')
    res = run("--output", "-", "--key", "id", "a.csv")
    assert lines(res.stdout) == ["id,v", '1,"a,b"', '2,"say ""hi"""', "3,plain"]


# Phrase: "Quote character defaults to \" ... overrideable via flags"
# Context: --csv-quotechar changes how inputs are parsed.
def test_csv_quotechar_parses_input(run, csv_file):
    csv_file("a.csv", "id,v\n1,'a,b'\n")
    res = run("--output", "-", "--key", "id", "--csv-quotechar", "'", "a.csv")
    assert column(res.stdout, "v") == ["a,b"]


# Phrase: "Deterministic Dialect Details: Output ... quote \"; escape by doubling quotes"
# Context: T7 — the output dialect stays canonical even when input used another quote.
def test_output_dialect_stays_canonical(run, csv_file):
    csv_file("a.csv", "id,v\n7,'a,b'\n")
    res = run("--output", "-", "--key", "id", "--csv-quotechar", "'", "a.csv")
    assert lines(res.stdout) == ["id,v", '7,"a,b"']


# Phrase: "escape character defaults to doubling the quote (\"\"), overrideable via flags"
# Context: --csv-escapechar switches input parsing to backslash-style escapes.
def test_csv_escapechar_parses_input(run, csv_file):
    csv_file("a.csv", 'id,v\n1,"say \\"hi\\""\n')
    res = run("--output", "-", "--key", "id", "--csv-escapechar", "\\", "a.csv")
    assert column(res.stdout, "v") == ['say "hi"']


# Phrase: "header row first"
# Context: the header precedes every data row in the output.
def test_header_is_first_row(run, csv_file):
    csv_file("a.csv", "id\n5\n")
    assert lines(run("--output", "-", "--key", "id", "a.csv").stdout)[0] == "id"


# Phrase: "All inputs are UTF-8, RFC-4180 compliant, with a header row"
# Context: T13 — ragged rows follow the same missing/extra rules as columns.
def test_ragged_rows_are_padded_and_truncated(run, csv_file):
    csv_file("a.csv", "id,a,b\n1,x\n2,x,y,z\n")
    res = run("--output", "-", "--key", "id", "a.csv")
    assert table(res.stdout) == [["a", "b", "id"], ["x", "", "1"], ["x", "y", "2"]]


# Phrase: "A command-line tool that ingests multiple CSVs"
# Context: a missing input file is an error, not a silent skip.
def test_missing_input_file_is_an_error(run, csv_file):
    csv_file("a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "a.csv", "nope.csv")
    assert res.returncode != 0
    assert "nope.csv" in res.stderr


# Phrase: "All inputs are UTF-8"
# Context: a UTF-8 BOM is not part of the first column's name.
def test_bom_is_not_part_of_the_header(run, tmp_path):
    (tmp_path / "a.csv").write_bytes("﻿id,v\n3,a\n".encode("utf-8"))
    res = run("--output", "-", "--key", "id", "a.csv")
    assert res.returncode == 0, res.stderr
    assert table(res.stdout) == [["id", "v"], ["3", "a"]]


# Phrase: "RFC-4180 compliant"
# Context: a blank line is not a record.
def test_blank_lines_are_not_rows(run, csv_file):
    csv_file("a.csv", "id,v\n3,a\n\n1,b\n")
    res = run("--output", "-", "--key", "id", "a.csv")
    assert table(res.stdout) == [["id", "v"], ["1", "b"], ["3", "a"]]


# Phrase: "line ending \n"
# Context: CRLF inputs still parse, and the output is normalized to \n.
def test_crlf_input_is_normalized(run, tmp_path):
    (tmp_path / "a.csv").write_bytes(b"id,v\r\n3,a\r\n1,b\r\n")
    res = run("--output", "-", "--key", "id", "a.csv")
    assert lines(res.stdout) == ["id,v", "1,b", "3,a"]
