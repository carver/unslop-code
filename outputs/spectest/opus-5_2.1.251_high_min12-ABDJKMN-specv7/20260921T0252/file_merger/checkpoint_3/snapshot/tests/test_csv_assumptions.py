"""Spec section: Fixed CSV assumptions."""
from conftest import run_tool, write_csv, write_file, col


# Phrase: "All inputs are UTF-8"
# Context: non-ASCII content must survive the round trip.
def test_utf8_input_round_trips(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "1,café", "2,日本語"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["café", "日本語"]


# Phrase: "All inputs are UTF-8"
# Context: a UTF-8 BOM in front of the header must not corrupt the first
# column name.
def test_utf8_bom_is_tolerated(tmp_path):
    path = write_file(tmp_path / "a.csv", "﻿id,name\n1,a\n")
    res = run_tool("--output", "-", "--key", "id", path)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["id", "name"]


# Phrase: "with a header row"
# Context: the first line names columns and is not emitted as data.
def test_header_row_is_not_data(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "1,a", "2,b"])
    res = run_tool("--output", "-", "--key", "id", src)
    rows = res.rows()
    assert rows[0] == ["id", "name"]
    assert len(rows) == 3


# Phrase: "with a header row"
# Context: every input carries its own header; headers are never rows.
def test_header_row_consumed_per_input_file(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    b = write_csv(tmp_path / "b.csv", ["id", "2"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.rows()[1:] == [["1"], ["2"]]


# Phrase: "with a header row"
# Context: a header-only input contributes no rows.
def test_header_only_input_contributes_no_rows(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,name"])
    b = write_csv(tmp_path / "b.csv", ["id,name", "7,x"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.rows() == [["id", "name"], ["7", "x"]]


# Phrase: "Delimiter is comma (,)"
# Context: fields are split on commas.
def test_comma_delimiter(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["a,b,c", "7,2,3"])
    res = run_tool("--output", "-", "--key", "a", src)
    assert res.rows()[1] == ["7", "2", "3"]


# Phrase: "line ending \n"
# Context: inputs use bare newlines.
def test_newline_line_endings(tmp_path):
    path = write_file(tmp_path / "a.csv", "id\n2\n1\n")
    res = run_tool("--output", "-", "--key", "id", path)
    assert col(res.rows(), "id") == ["1", "2"]


# Phrase: "Quote character defaults to \""
# Context: a quoted field containing the delimiter stays one field.
def test_default_quotechar_protects_delimiter(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['id,note', '7,"a,b"'])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.rows()[1] == ["7", "a,b"]


# Phrase: "escape character defaults to doubling the quote ("")"
# Context: a doubled quote inside a quoted field decodes to one quote.
def test_default_escape_is_doubled_quote(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['id,note', '7,"say ""hi"""'])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.rows()[1] == ["7", 'say "hi"']


# Phrase: "and accepts backslash-escapes (\")"
# Context: by default a backslash escaped quote inside a quoted field also
# decodes to one quote.
def test_backslash_escaped_quote_accepted_by_default(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['id,note', '7,"say \\"hi\\""'])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["7", 'say "hi"']


# Phrase: "overrideable via flags"
# Context: --csv-quotechar changes the input quote character.
def test_csv_quotechar_override(tmp_path):
    from conftest import parse_csv_dialect
    src = write_csv(tmp_path / "a.csv", ["id,note", "7,'a,b'"])
    res = run_tool("--output", "-", "--key", "id",
                   "--csv-quotechar", "'", src)
    assert res.returncode == 0, res.stderr
    # Checkpoint 2 makes the flag apply to the writer too (see T1/T29).
    assert parse_csv_dialect(res.stdout, quotechar="'")[1] == ["7", "a,b"]


# Phrase: "overrideable via flags"
# Context: --csv-escapechar changes the input escape character.
def test_csv_escapechar_override(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['id,note', '7,"a|"b"'])
    res = run_tool("--output", "-", "--key", "id",
                   "--csv-escapechar", "|", src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1] == ["7", 'a"b']


# Phrase: "RFC-4180 compliant"
# Context: an empty quoted field is an empty value.
def test_empty_quoted_field(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['id,note', '7,""'])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.rows()[1] == ["7", ""]
