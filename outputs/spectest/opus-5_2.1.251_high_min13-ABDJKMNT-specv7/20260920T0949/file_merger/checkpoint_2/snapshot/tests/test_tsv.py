"""The TSV source dialect."""

from conftest import rows_of


# Spec: "**TSV**: delimiter is tab (`\t`)"
def test_fields_are_split_on_tabs(make_text, run):
    make_text("a.tsv", "id\tname\n7\tada\n")
    proc = run("--output", "-", "--key", "id", "a.tsv")
    assert rows_of(proc.stdout) == [["id", "name"], ["7", "ada"]]


# Spec: "**TSV**: ... `\n` or `\r\n` line endings"
def test_crlf_line_endings_are_accepted(make_text, run):
    make_text("a.tsv", "id\tname\r\n2\tbo\r\n1\tal\r\n")
    proc = run("--output", "-", "--key", "id", "a.tsv")
    assert rows_of(proc.stdout) == [["id", "name"], ["1", "al"], ["2", "bo"]]


# Spec: "**TSV**: ... header row required"
# Context: the first line names the columns of the merged schema.
def test_header_row_names_the_columns(make_text, run):
    make_text("a.tsv", "b\ta\n5\t2\n")
    proc = run("--output", "-", "--key", "a", "a.tsv")
    assert rows_of(proc.stdout) == [["a", "b"], ["2", "5"]]


# Spec: "**TSV**: ... no quoting"
# Context: see AMBIGUITIES T26 - quote characters are ordinary data in a TSV field.
def test_quote_characters_are_literal_data(make_text, run):
    make_text("a.tsv", 'id\tname\n7\t"ada, lovelace"\n')
    proc = run("--output", "-", "--key", "id", "a.tsv")
    assert rows_of(proc.stdout)[1] == ["7", '"ada, lovelace"']


# Spec: "**TSV**: ... literal tabs inside field not allowed (error 5)"
# Context: see AMBIGUITIES T25 - a stray tab shows up as a surplus field.
def test_row_with_more_fields_than_the_header_exits_5(make_text, run):
    make_text("a.tsv", "id\tname\n1\tada\tlovelace\n")
    proc = run("--output", "-", "--key", "id", "a.tsv", expect_ok=False)
    assert proc.returncode == 5
    assert proc.stderr.strip()


# Spec: "**TSV**: ... header row required" with "Missing columns filled with null literal"
# Context: see AMBIGUITIES T25 - a short row is padded, as a missing column is.
def test_short_row_is_padded_with_the_null_literal(make_text, run):
    make_text("a.tsv", "id\tname\n7\n")
    proc = run("--output", "-", "--key", "id", "--csv-null-literal", "NA", "a.tsv")
    assert rows_of(proc.stdout)[1] == ["7", "NA"]


# Spec: "CSV/TSV values are raw strings" with "If ... CSV/TSV cell is empty, treat as missing"
def test_empty_tsv_cell_is_missing(make_text, run):
    make_text("a.tsv", "id\tname\n7\t\n")
    proc = run("--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.tsv")
    assert rows_of(proc.stdout)[1] == ["7", "NULL"]


# Spec: "**TSV**: ... header row required"
# Context: see AMBIGUITIES T37 - a TSV without a header line is a dialect violation.
def test_tsv_without_a_header_exits_5(make_text, run):
    make_text("a.tsv", "")
    proc = run("--output", "-", "--key", "id", "a.tsv", expect_ok=False)
    assert proc.returncode == 5


# Spec: "CSV/TSV values are raw strings (after unescape for CSV)"
# Context: TSV text is typed by the same inference as CSV text.
def test_tsv_values_take_part_in_type_inference(make_text, run):
    make_text("a.tsv", "id\n10\n9\n")
    proc = run("--output", "-", "--key", "id", "a.tsv")
    assert rows_of(proc.stdout)[1:] == [["9"], ["10"]]
