"""Input parsing dialect and the deterministic output dialect."""

from conftest import rows_of


# Spec: "Output delimiter `,`, quote `"`; escape by doubling quotes; `\n` line endings; header row first"
def test_output_uses_commas_doubled_quotes_and_newlines(make_csv, run, workdir):
    make_csv("a.csv", 'id,note\n7,"a,b"\n')
    run("--output", "out.csv", "--key", "id", "a.csv")
    raw = (workdir / "out.csv").read_bytes()
    assert raw == b'id,note\n7,"a,b"\n'


# Spec: "escape by doubling quotes"
def test_embedded_quotes_are_doubled_on_output(make_csv, run):
    make_csv("a.csv", 'id,note\n7,"he said ""hi"""\n')
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert proc.stdout == 'id,note\n7,"he said ""hi"""\n'


# Spec: "escape character defaults to doubling the quote (`""`) and accepts backslash-escapes (`\"`)"
# Context: see AMBIGUITIES T1 - backslash escaping is accepted on input by default.
def test_backslash_escaped_quotes_are_accepted_on_input(make_csv, run):
    make_csv("a.csv", 'id,note\n7,"he said \\"hi\\""\n')
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert rows_of(proc.stdout)[1] == ["7", 'he said "hi"']


# Spec: "Quote character defaults to `"`"
def test_quoted_fields_may_contain_the_delimiter(make_csv, run):
    make_csv("a.csv", 'id,note\n7,"a,b"\n')
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert rows_of(proc.stdout)[1] == ["7", "a,b"]


# Spec: "Quote character defaults to `"` ... overrideable via flags" (--csv-quotechar)
def test_quote_character_override_is_used_when_reading(make_csv, run):
    make_csv("a.csv", "id,note\n7,'a,b'\n")
    proc = run("--output", "-", "--key", "id", "--csv-quotechar", "'", "a.csv")
    assert rows_of(proc.stdout)[1] == ["7", "a,b"]


# Spec: "escape character ... overrideable via flags" (--csv-escapechar)
def test_escape_character_override_is_used_when_reading(make_csv, run):
    make_csv("a.csv", 'id,note\n7,"a~"b"\n')
    proc = run("--output", "-", "--key", "id", "--csv-escapechar", "~", "a.csv")
    assert rows_of(proc.stdout)[1] == ["7", 'a"b']


# Spec: "Output delimiter `,`, quote `"`" under "Deterministic Dialect Details"
# Context: see AMBIGUITIES T2 - the output dialect stays canonical even when the
# input dialect flags are overridden.
def test_output_quoting_stays_canonical_under_quotechar_override(make_csv, run):
    make_csv("a.csv", "id,note\n7,'a,b'\n")
    proc = run("--output", "-", "--key", "id", "--csv-quotechar", "'", "a.csv")
    assert proc.stdout == 'id,note\n7,"a,b"\n'


# Spec: "All inputs are UTF-8"
def test_utf8_content_round_trips(make_csv, run):
    make_csv("a.csv", "id,note\n7,café ☕\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert rows_of(proc.stdout)[1] == ["7", "café ☕"]


# Spec: "with a header row"
# Context: the first line names the columns and is never treated as data.
def test_header_row_is_not_emitted_as_data(make_csv, run):
    make_csv("a.csv", "id\n7\n")
    make_csv("b.csv", "id\n8\n")
    proc = run("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert rows_of(proc.stdout) == [["id"], ["7"], ["8"]]


# Spec: "RFC-4180 compliant, with a header row"
# Context: see AMBIGUITIES T15 - a blank line is not a record.
def test_blank_lines_are_not_emitted_as_rows(make_csv, run):
    make_csv("a.csv", "id,note\n7,x\n\n8,y\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert rows_of(proc.stdout) == [["id", "note"], ["7", "x"], ["8", "y"]]


# Spec: "Missing columns in a file filled with null literal"
# Context: see AMBIGUITIES T17 - a short row is padded, a long one is truncated.
def test_ragged_rows_are_padded_and_truncated(make_csv, run):
    make_csv("a.csv", "id,note\n7\n8,x,extra\n")
    proc = run("--output", "-", "--key", "id", "a.csv")
    assert rows_of(proc.stdout) == [["id", "note"], ["7", ""], ["8", "x"]]


# Spec: "with a **header row**"
# Context: see AMBIGUITIES T18 - an empty file contributes nothing.
def test_empty_input_file_contributes_nothing(make_csv, run):
    make_csv("a.csv", "id\n7\n")
    make_csv("empty.csv", "")
    proc = run("--output", "-", "--key", "id", "a.csv", "empty.csv")
    assert rows_of(proc.stdout) == [["id"], ["7"]]
