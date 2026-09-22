"""Spec sections: Fixed CSV assumptions / Deterministic Dialect Details."""
from conftest import body, header, parse_csv_text


# Phrase: "All inputs are UTF-8, RFC-4180 compliant, with a header row"
# Context: Fixed CSV assumptions.
def test_utf8_inputs_round_trip(run, work):
    work.write("a.csv", "id,name\n2,café\n1,naïve\n")
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["1", "naïve"], ["2", "café"]]


def test_header_row_defines_columns(run, work):
    work.write("a.csv", "beta,alpha\n1,2\n")
    r = run("--output", "-", "--key", "alpha", work.path("a.csv"))
    assert r.ok, r.stderr
    assert header(r) == ["alpha", "beta"]


# Phrase: "Delimiter is comma (`,`); line ending `\n`"
# Context: Fixed CSV assumptions + Deterministic Dialect Details.
def test_output_uses_comma_delimiter_and_newline_endings(run, work):
    work.csv("a.csv", ["id", "v"], [["7", "x"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert r.stdout == "id,v\n7,x\n"
    assert "\r" not in r.stdout


def test_output_file_uses_newline_endings(run, work):
    work.csv("a.csv", ["id"], [["1"], ["2"]])
    out = work.path("o.csv")
    r = run("--output", out, "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.read_bytes() == b"id\n1\n2\n"


# Phrase: "Quote character defaults to `\"`"
# Context: Fixed CSV assumptions; quoted fields containing the delimiter parse as one field.
def test_quoted_field_containing_comma(run, work):
    work.write("a.csv", 'id,note\n7,"a,b"\n')
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["7", "a,b"]]


# Phrase: "escape character defaults to doubling the quote (`\"\"`)"
# Context: Fixed CSV assumptions.
def test_doubled_quote_escape_on_input(run, work):
    work.write("a.csv", 'id,note\n7,"say ""hi"""\n')
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["7", 'say "hi"']]


# Phrase: "and accepts backslash-escapes (`\\\"`)"
# Context: Fixed CSV assumptions; both escaping styles are accepted on input.
def test_backslash_quote_escape_on_input(run, work):
    work.write("a.csv", 'id,note\n7,"say \\"hi\\""\n')
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["7", 'say "hi"']]


# Phrase: "overrideable via flags" (--csv-quotechar)
# Context: Fixed CSV assumptions. Checkpoint 2 adds "Use configured CSV dialect
# flags for output quoting/escaping", so the same character quotes the output.
def test_csv_quotechar_override_on_input(run, work):
    work.write("a.csv", "id,note\n7,'a,b'\n")
    r = run(
        "--output", "-", "--key", "id", "--csv-quotechar", "'", work.path("a.csv")
    )
    assert r.ok, r.stderr
    assert r.stdout == "id,note\n7,'a,b'\n"


# Phrase: "overrideable via flags" (--csv-escapechar)
# Context: Fixed CSV assumptions.
def test_csv_escapechar_override_on_input(run, work):
    work.write("a.csv", 'id,note\n7,"a!"b"\n')
    r = run(
        "--output", "-", "--key", "id", "--csv-escapechar", "!", work.path("a.csv")
    )
    assert r.ok, r.stderr
    assert body(r) == [["7", 'a"b']]


# Phrase: "Output delimiter `,`, quote `\"`; escape by doubling quotes"
# Context: Deterministic Dialect Details; output quoting is minimal and uses doubling.
def test_output_escapes_by_doubling_quotes(run, work):
    work.write("a.csv", 'id,note\n7,"say ""hi"""\n')
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert r.stdout == 'id,note\n7,"say ""hi"""\n'


def test_output_quotes_fields_containing_delimiter(run, work):
    work.write("a.csv", 'id,note\n7,"a,b"\n')
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert r.stdout == 'id,note\n7,"a,b"\n'


# Phrase: "header row first"
# Context: Deterministic Dialect Details.
def test_header_is_first_line(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "x"], ["2", "y"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert r.stdout.splitlines()[0] == "id,v"


# Phrase: "No multiline fields will be present in tests"
# Context: Fixed CSV assumptions; every output record is one physical line.
def test_row_count_matches_line_count(run, work):
    work.csv("a.csv", ["id"], [["1"], ["2"], ["3"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert len(r.stdout.splitlines()) == 4
