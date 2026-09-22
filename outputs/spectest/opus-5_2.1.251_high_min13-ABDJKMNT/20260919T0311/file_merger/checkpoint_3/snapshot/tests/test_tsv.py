"""Spec section: Source Dialect Assumptions — TSV."""
from conftest import column, table


# Phrase: "TSV: delimiter is tab (\t)"
def test_tab_delimited_fields(run, text_file):
    text_file("a.tsv", "id\tname\tcity\n7\tada\tlondon\n")
    res = run("--output", "-", "--key", "id", "a.tsv")
    assert table(res.stdout) == [["city", "id", "name"], ["london", "7", "ada"]]


# Phrase: "TSV: ... no quoting"
# Context: a double quote is ordinary data in a TSV field, never a quote character.
def test_quotes_are_literal_data(run, text_file):
    text_file("a.tsv", 'id\tv\n1\t"a,b"\n2\tsay "hi"\n')
    res = run("--output", "-", "--key", "id", "a.tsv")
    assert column(res.stdout, "v") == ['"a,b"', 'say "hi"']


# Phrase: "TSV: ... header row required"
# Context: the first line names the columns, exactly as for CSV.
def test_header_row_names_the_columns(run, text_file):
    text_file("a.tsv", "b\ta\n2\t1\n")
    assert table(run("--output", "-", "--key", "a", "a.tsv").stdout)[0] == ["a", "b"]


# Phrase: "TSV: ... \n line endings"
def test_lf_line_endings(run, text_file):
    text_file("a.tsv", "id\tv\n2\ty\n1\tx\n")
    assert column(run("--output", "-", "--key", "id", "a.tsv").stdout, "v") == ["x", "y"]


# Phrase: "literal tabs inside field not allowed (error 5)"
# Context: T27 — the symptom is a row with more fields than the header.
def test_extra_tab_in_row_is_error_5(run, text_file):
    text_file("a.tsv", "id\tv\n1\ta\tb\n")
    res = run("--output", "-", "--key", "id", "a.tsv")
    assert res.returncode == 5
    assert res.stderr.strip().startswith("error:")


# Phrase: "literal tabs inside field not allowed"
# Context: T27 — a short row is not the flagged condition; it null-fills (T13).
def test_short_row_fills_with_null(run, text_file):
    text_file("a.tsv", "id\tv\n1\n")
    res = run("--output", "-", "--key", "id", "a.tsv")
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "v") == [""]


# Phrase: "CSV/TSV values are raw strings"
# Context: TSV text is typed by inference exactly like CSV text.
def test_tsv_values_are_inferred_like_csv_text(run, text_file):
    text_file("a.tsv", "n\n10\n9\n")
    assert column(run("--output", "-", "--key", "n", "a.tsv").stdout, "n") == ["9", "10"]


# Phrase: "If ... CSV/TSV cell is empty, treat as missing -> emit null literal"
def test_empty_tsv_cell_is_null(run, text_file):
    text_file("a.tsv", "id\tv\n1\t\n")
    res = run("--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.tsv")
    assert column(res.stdout, "v") == ["NULL"]
