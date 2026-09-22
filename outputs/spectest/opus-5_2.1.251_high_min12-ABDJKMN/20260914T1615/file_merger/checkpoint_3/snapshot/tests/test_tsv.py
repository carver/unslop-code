"""Spec section: Source Dialect Assumptions — TSV."""

from conftest import (body, col, header, run, run_ok, write, write_schema,
                      write_tsv)


# --- Spec: "TSV: delimiter is tab (`\t`)" ---
# Context: Source Dialect Assumptions; fields split on tabs only.
def test_tsv_splits_on_tabs(ws):
    a = write_tsv(ws / "a.tsv", ["id", "note"], [["7", "a,b"]])
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["id", "note"]
    # A comma inside a TSV field is data, and is quoted on CSV output.
    assert body(res.stdout) == ['7,"a,b"']


# --- Spec: "TSV: ... no quoting" ---
# Context: Source Dialect Assumptions; a double quote is an ordinary character.
def test_tsv_has_no_quoting(ws):
    a = write_tsv(ws / "a.tsv", ["id", "note"], [["1", '"hi"']])
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "note") == ['"hi"']


# --- Spec: "TSV: ... no quoting" ---
# Context: Source Dialect Assumptions; a quote mid-field is not special either.
def test_tsv_quote_inside_field_is_literal(ws):
    a = write_tsv(ws / "a.tsv", ["id", "note"], [["1", 'say "hi" now']])
    res = run_ok("--output", "-", "--key", "id", a)
    assert col(res.stdout, "note") == ['say "hi" now']


# --- Spec: "TSV: ... header row required" ---
# Context: Source Dialect Assumptions; the first line names the columns.
def test_tsv_header_row_names_columns(ws):
    a = write_tsv(ws / "a.tsv", ["b", "a"], [["4", "3"]])
    res = run_ok("--output", "-", "--key", "a", a)
    assert header(res.stdout) == ["a", "b"]
    assert body(res.stdout) == ["3,4"]


# --- Spec: "TSV: ... `\n` line endings" ---
# Context: Source Dialect Assumptions.
def test_tsv_lf_line_endings(ws):
    a = write(ws / "a.tsv", "id\tv\n2\tb\n1\ta\n")
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "literal tabs inside field not allowed (error 5)" ---
# Context: Source Dialect Assumptions, TSV. A row wider than the header is the
# only observable trace of an embedded tab (see T29).
def test_tsv_literal_tab_in_field_is_error_5(ws):
    a = write(ws / "a.tsv", "id\tv\n1\ta\tb\n")
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 5
    assert res.stderr.strip() != ""


# --- Spec: "TSV" values are raw strings cast per the resolved schema ---
# Context: Casting; "CSV/TSV values are raw strings".
def test_tsv_values_are_typed_by_inference(ws):
    a = write_tsv(ws / "a.tsv", ["id", "amt"], [["2", "1.50"], ["10", "3"]])
    res = run_ok("--output", "-", "--key", "id", a)
    # numeric sort, and float rendering per checkpoint 1
    assert col(res.stdout, "id") == ["2", "10"]
    assert col(res.stdout, "amt") == ["1.5", "3.0"]


# --- Spec: "If ... CSV/TSV cell is empty, treat as missing → emit null literal" ---
# Context: Casting.
def test_tsv_empty_cell_is_null(ws):
    a = write_tsv(ws / "a.tsv", ["id", "v"], [["1", ""]])
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "NULL", a)
    assert col(res.stdout, "v") == ["NULL"]


# --- Spec: TSV is one of the accepted file types alongside CSV ---
# Context: New Input Types; CSV and TSV columns union normally.
def test_tsv_and_csv_merge(ws):
    a = write_tsv(ws / "a.tsv", ["id", "x"], [["1", "a"]])
    b = write(ws / "b.csv", "id,y\n2,c\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert header(res.stdout) == ["id", "x", "y"]
    assert body(res.stdout) == ["1,a,", "2,,c"]


# --- Spec: "--input-format tsv --compression gzip data/*.tsv.gz" ---
# Context: Examples; the documented forced-TSV + forced-gzip invocation.
def test_forced_tsv_gzip_example(ws):
    from conftest import gzip_existing
    p1 = write_tsv(ws / "one.tsv", ["created_at", "id"],
                   [["2024-07-01T00:00:00Z", "1"]])
    p2 = write_tsv(ws / "two.tsv", ["created_at", "id"],
                   [["2024-07-02T00:00:00Z", "2"]])
    g1 = gzip_existing(p1, ws / "one.tsv.gz")
    g2 = gzip_existing(p2, ws / "two.tsv.gz")
    s = write_schema(ws / "s.json",
                     [("created_at", "timestamp"), ("id", "int")])
    res = run_ok("--output", "-", "--key", "created_at,id", "--desc",
                 "--schema", s, "--input-format", "tsv",
                 "--compression", "gzip", g1, g2)
    assert col(res.stdout, "id") == ["2", "1"]


# --- Spec: a TSV row with fewer fields than the header ---
# Context: Source Dialect Assumptions; short rows pad with nulls (see T29/T16).
def test_tsv_short_row_pads_with_nulls(ws):
    a = write(ws / "a.tsv", "id\tv\tw\n7\ta\n")
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["7,a,"]


# --- Spec: "TSV: ... header row required" with no data rows ---
# Context: Source Dialect Assumptions; columns still contribute (see T43).
def test_tsv_header_only_contributes_columns(ws):
    a = write(ws / "a.tsv", "id\tv\n")
    b = write(ws / "b.csv", "id\n7\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert header(res.stdout) == ["id", "v"]
    assert body(res.stdout) == ["7,"]
