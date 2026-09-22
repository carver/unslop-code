"""Spec sections: Fixed CSV assumptions and Deterministic Dialect Details."""

from conftest import rows_of


# Phrase: "Delimiter is comma (,); line ending \n"
# Context: Deterministic Dialect Details, output side.
def test_output_uses_commas_and_newlines(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,note\n1,a\n2,b\n")
    run_tool("--output", "out.csv", "--key", "id", "a.csv")
    raw = (workdir / "out.csv").read_bytes()
    assert raw == b"id,note\n1,a\n2,b\n"


# Phrase: "Output delimiter ,, quote "; escape by doubling quotes"
# Context: Deterministic Dialect Details. Quotes appear only where needed.
def test_output_quotes_only_when_required(csv_file, run_tool, workdir):
    csv_file("a.csv", 'id,note\n1,"has, comma"\n2,"has ""quotes"""\n')
    run_tool("--output", "out.csv", "--key", "id", "a.csv")
    raw = (workdir / "out.csv").read_text(encoding="utf-8")
    assert raw == 'id,note\n1,"has, comma"\n2,"has ""quotes"""\n'


# Phrase: "escape character defaults to doubling the quote ("")"
# Context: Fixed CSV assumptions, input side.
def test_doubled_quotes_are_read_as_one_quote(csv_file, run_tool):
    csv_file("a.csv", 'id,note\n7,"say ""hi"""\n')
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert rows_of(result.stdout) == [["7", 'say "hi"']]


# Phrase: "and accepts backslash-escapes (\")"
# Context: Fixed CSV assumptions, input side. Ambiguity T11.
def test_backslash_escaped_quotes_are_read(csv_file, run_tool):
    csv_file("a.csv", 'id,note\n7,"say \\"hi\\""\n')
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert rows_of(result.stdout) == [["7", 'say "hi"']]


# Phrase: "Quote character defaults to " ... overrideable via flags"
# Context: Fixed CSV assumptions. --csv-quotechar changes how inputs are parsed.
def test_quotechar_override_changes_input_parsing(csv_file, run_tool):
    csv_file("a.csv", "id,note\n7,'has, comma'\n")
    result = run_tool("--output", "-", "--key", "id", "--csv-quotechar", "'", "a.csv")
    assert rows_of(result.stdout) == [["7", "has, comma"]]


# Phrase: "escape character ... overrideable via flags"
# Context: Fixed CSV assumptions. --csv-escapechar selects the escape character.
def test_escapechar_override_changes_input_parsing(csv_file, run_tool):
    csv_file("a.csv", "id,note\n7,a~,b\n")
    result = run_tool("--output", "-", "--key", "id", "--csv-escapechar", "~", "a.csv")
    assert rows_of(result.stdout) == [["7", "a,b"]]


# Phrase: "Output delimiter ,, quote "; escape by doubling quotes"
# Context: Deterministic Dialect Details. Ambiguity T10: input flags leave output alone.
def test_output_dialect_ignores_the_input_overrides(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,note\n7,'has, comma'\n")
    run_tool(
        "--output", "out.csv", "--key", "id", "--csv-quotechar", "'", "a.csv"
    )
    raw = (workdir / "out.csv").read_text(encoding="utf-8")
    assert raw == 'id,note\n7,"has, comma"\n'


# Phrase: "All inputs are UTF-8"
# Context: Fixed CSV assumptions. A byte-order mark is not part of the first name.
def test_utf8_bom_is_stripped_from_the_header(csv_file, run_tool, workdir):
    (workdir / "a.csv").write_bytes("﻿id,note\n7,a\n".encode("utf-8"))
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "id,note\n7,a\n"


# Phrase: "header row first"
# Context: Deterministic Dialect Details.
def test_header_is_the_first_output_line(csv_file, run_tool):
    csv_file("a.csv", "id,note\n2,b\n1,a\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.stdout.splitlines()[0] == "id,note"


# Phrase: "Output delimiter ,, quote ""
# Context: Deterministic Dialect Details. Values equal to the null literal are plain text.
def test_null_literal_is_written_without_quoting(csv_file, run_tool):
    csv_file("a.csv", "id,note\n7,\n")
    result = run_tool("--output", "-", "--key", "id", "--csv-null-literal", "N/A", "a.csv")
    assert result.stdout == "id,note\n7,N/A\n"
