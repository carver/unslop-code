"""Spec section: Source Dialect Assumptions — the TSV dialect."""

from conftest import column, header_of, rows_of


# Phrase: "TSV: delimiter is tab (\t) ... header row required"
# Context: Source Dialect Assumptions.
def test_tsv_splits_on_tabs_and_reads_a_header(tsv_file, run_tool):
    tsv_file("a.tsv", "id\tnote\n2\tbee\n1\tay\n")
    result = run_tool("--output", "-", "--key", "id", "a.tsv")
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "note"]
    assert rows_of(result.stdout) == [["1", "ay"], ["2", "bee"]]


# Phrase: "no quoting"
# Context: Source Dialect Assumptions, TSV. Quote characters are ordinary data.
def test_tsv_treats_quotes_as_data(tsv_file, run_tool):
    tsv_file("a.tsv", 'id\tnote\n7\t"quoted, text"\n')
    result = run_tool("--output", "-", "--key", "id", "a.tsv")
    assert rows_of(result.stdout) == [["7", '"quoted, text"']]


# Phrase: "\n or \r\n line endings"
# Context: Source Dialect Assumptions, TSV. The carriage return is not data.
def test_tsv_accepts_crlf_line_endings(tsv_file, run_tool):
    tsv_file("a.tsv", "id\tnote\r\n2\tbee\r\n1\tay\r\n")
    result = run_tool("--output", "-", "--key", "id", "a.tsv")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1", "ay"], ["2", "bee"]]


# Phrase: "literal tabs inside field not allowed (error 5)"
# Context: Source Dialect Assumptions, TSV. Ambiguity T31: surplus fields reveal one.
def test_tsv_row_with_extra_tab_is_error_5(tsv_file, run_tool):
    tsv_file("a.tsv", "id\tnote\n1\thas\textra\n")
    result = run_tool("--output", "-", "--key", "id", "a.tsv")
    assert result.returncode == 5
    assert result.stderr


# Phrase: "header row required"
# Context: Source Dialect Assumptions, TSV. Ambiguity T31: an empty file has no header.
def test_tsv_without_a_header_is_error_5(tsv_file, run_tool):
    tsv_file("a.tsv", "")
    result = run_tool("--output", "-", "--key", "id", "a.tsv")
    assert result.returncode == 5
    assert result.stderr


# Phrase: "CSV/TSV values are raw strings"
# Context: Casting. TSV text is inferred and cast exactly like CSV text.
def test_tsv_values_are_inferred_like_csv(tsv_file, run_tool):
    tsv_file("a.tsv", "id\n100\n9\n20\n")
    result = run_tool("--output", "-", "--key", "id", "a.tsv")
    assert column(result.stdout, "id") == ["9", "20", "100"]


# Phrase: "If ... CSV/TSV cell is empty, treat as missing -> emit null literal"
# Context: Casting. An empty tab-separated field is a missing value.
def test_tsv_empty_field_is_null(tsv_file, run_tool):
    tsv_file("a.tsv", "id\tnote\n7\t\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.tsv"
    )
    assert rows_of(result.stdout) == [["7", "NULL"]]


# Phrase: "Accepted file types: CSV, TSV"
# Context: New Input Types. A short TSV row leaves its trailing columns null.
def test_tsv_short_row_fills_missing_columns(tsv_file, run_tool):
    tsv_file("a.tsv", "id\tnote\n7\n")
    result = run_tool("--output", "-", "--key", "id", "a.tsv")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["7", ""]]
