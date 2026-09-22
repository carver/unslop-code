"""Spec section: Source Dialect Assumptions - TSV."""
from conftest import body, header


# Phrase: "TSV: delimiter is tab (`\t`) ... header row required"
# Context: Source Dialect Assumptions.
def test_tsv_splits_on_tabs_with_header(run, work):
    work.tsv("a.tsv", ["id", "name"], [["2", "bee"], ["1", "ay"]])
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.ok, r.stderr
    assert header(r) == ["id", "name"]
    assert body(r) == [["1", "ay"], ["2", "bee"]]


# Phrase: "no quoting"
# Context: Source Dialect Assumptions - TSV; quote characters are literal data.
def test_tsv_quotes_are_literal(run, work):
    work.tsv("a.tsv", ["id", "note"], [["3", '"hi there"']])
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.ok, r.stderr
    assert body(r) == [["3", '"hi there"']]


def test_tsv_commas_are_literal(run, work):
    work.tsv("a.tsv", ["id", "note"], [["3", "a,b,c"]])
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.ok, r.stderr
    assert body(r) == [["3", "a,b,c"]]
    # and the comma is re-quoted on CSV output
    assert r.stdout == 'id,note\n3,"a,b,c"\n'


# Phrase: "`\n` or `\r\n` line endings"
# Context: Source Dialect Assumptions - TSV.
def test_tsv_accepts_crlf_line_endings(run, work):
    work.tsv("a.tsv", ["id", "name"], [["2", "b"], ["1", "a"]], newline="\r\n")
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.ok, r.stderr
    assert header(r) == ["id", "name"]
    assert body(r) == [["1", "a"], ["2", "b"]]


def test_tsv_crlf_does_not_leak_carriage_return(run, work):
    work.tsv("a.tsv", ["id"], [["9"]], newline="\r\n")
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.ok, r.stderr
    assert r.stdout == "id\n9\n"


# Phrase: "literal tabs inside field not allowed (error 5)"
# Context: Source Dialect Assumptions - TSV; surfaces as a row with too many fields.
def test_tsv_extra_field_is_error_5(run, work):
    work.write("a.tsv", "id\tname\n1\tone\ttwo\n")
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.returncode == 5
    assert r.stderr.strip()


# Phrase: "header row required"
# Context: Source Dialect Assumptions - TSV; an empty file has no header.
def test_tsv_empty_file_is_error_5(run, work):
    work.write("a.tsv", "")
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.returncode == 5


# Phrase: "Missing columns filled with null literal" (Schema Resolution)
# Context: TSV rows shorter than the header.
def test_tsv_short_row_fills_nulls(run, work):
    work.write("a.tsv", "id\tname\n5\n")
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.ok, r.stderr
    assert body(r) == [["5", ""]]


# Phrase: "CSV/TSV values are raw strings"
# Context: Casting; TSV cells are typed by inference just like CSV cells.
def test_tsv_values_are_inferred_and_cast(run, work):
    work.tsv("a.tsv", ["id", "amount"], [["2", "1.5"], ["10", "0.25"]])
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.ok, r.stderr
    # columns are ordered lexicographically; numeric (not lexicographic) row
    # ordering proves the int cast of the key
    assert header(r) == ["amount", "id"]
    assert body(r) == [["1.5", "2"], ["0.25", "10"]]


# Phrase: "If ... CSV/TSV cell is empty, treat as missing -> emit null literal"
# Context: Casting.
def test_tsv_empty_cell_is_null(run, work):
    work.tsv("a.tsv", ["id", "amount"], [["5", ""]])
    r = run(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL",
        work.path("a.tsv"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["amount", "id"]
    assert body(r) == [["NULL", "5"]]


# Phrase: "Authoritative provided schema, TSV source, gzip forced, descending sort"
# Context: Examples; the documented invocation shape must work.
def test_documented_tsv_example(run, work):
    work.schema("schema.json", [("created_at", "timestamp"), ("id", "int")])
    work.gzip(
        "d1.tsv.gz", "id\tcreated_at\n1\t2024-07-01T00:00:00Z\n2\t2024-07-03T00:00:00Z\n"
    )
    work.gzip("d2.tsv.gz", "id\tcreated_at\n3\t2024-07-02T00:00:00Z\n")
    r = run(
        "--output", "-", "--key", "created_at,id", "--desc",
        "--schema", work.path("schema.json"),
        "--input-format", "tsv", "--compression", "gzip",
        work.path("d1.tsv.gz"), work.path("d2.tsv.gz"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["created_at", "id"]
    assert [row[1] for row in body(r)] == ["2", "3", "1"]
