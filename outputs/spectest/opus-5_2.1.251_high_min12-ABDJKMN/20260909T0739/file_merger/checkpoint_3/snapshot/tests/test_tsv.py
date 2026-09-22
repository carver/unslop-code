"""`Source Dialect Assumptions`: TSV."""
from conftest import merge_paths, write, write_tsv


# --- Spec: "TSV: delimiter is tab (`\t`) ... header row required" ---------
def test_tsv_header_and_tab_delimiter(tmp_path):
    a = write_tsv(tmp_path, "a.tsv", [["id", "name"], ["1", "alice"],
                                      ["2", "bob"]])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["1", "alice"], ["2", "bob"]]


# --- Spec: "TSV: ... no quoting" - double quotes are ordinary characters ---
def test_tsv_quotes_are_literal_characters(tmp_path):
    a = write(tmp_path, "a.tsv", 'id\tname\n7\t"quoted"\n')
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["7", '"quoted"']


def test_tsv_comma_is_data_not_delimiter(tmp_path):
    a = write(tmp_path, "a.tsv", "id\tname\n7\ta,b\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["7", "a,b"]


# --- Spec: "TSV: ... `\n` line endings" ------------------------------------
def test_tsv_newline_separated_records(tmp_path):
    a = write(tmp_path, "a.tsv", "id\tv\n1\ta\n2\tb\n3\tc\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert [row[0] for row in r.rows()[1:]] == ["1", "2", "3"]


# --- Spec: "literal tabs inside field not allowed (error 5)" --------------
def test_extra_tab_in_data_row_is_error_5(tmp_path):
    a = write(tmp_path, "a.tsv", "id\tname\n1\tal\tice\n")
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 5, r
    assert r.stderr.strip()


def test_tsv_row_matching_header_width_is_fine(tmp_path):
    a = write(tmp_path, "a.tsv", "id\tname\tx\n1\ta\tb\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r


# --- Spec: "TSV: ... header row required" - the first line names columns ---
def test_tsv_header_defines_columns(tmp_path):
    a = write_tsv(tmp_path, "a.tsv", [["b", "a"], ["20", "10"]])
    r = merge_paths([a], "--key", "a")
    assert r.ok, r
    # Inferred column order is lexicographic, not header order.
    assert r.rows()[0] == ["a", "b"]
    assert r.rows()[1] == ["10", "20"]


# --- Spec: "CSV/TSV values are raw strings" - TSV cells are cast like CSV --
def test_tsv_values_are_cast_like_csv(tmp_path):
    a = write_tsv(tmp_path, "a.tsv", [["id", "amount"], ["7", "2.50"]])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[0] == ["amount", "id"]
    assert r.rows()[1] == ["2.5", "7"]


# --- Spec: "CSV/TSV cell is empty ... treat as missing -> emit null literal"
def test_tsv_empty_cell_is_null(tmp_path):
    a = write(tmp_path, "a.tsv", "id\tname\n7\t\n")
    r = merge_paths([a], "--key", "id", "--csv-null-literal", "NULL")
    assert r.ok, r
    assert r.rows()[1] == ["7", "NULL"]


# --- Spec: TSV rows shorter than the header keep checkpoint 1's padding ----
def test_tsv_short_row_is_padded_with_nulls(tmp_path):
    a = write(tmp_path, "a.tsv", "id\tname\n7\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["7", ""]
