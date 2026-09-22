"""`Schema Resolution & Column Order`, branch 2: inference."""
from conftest import merge, run, write


# --- Spec: "If `--schema` not provided: infer schema from union of all input
#            headers" ------------------------------------------------------
def test_union_of_all_input_headers(tmp_path):
    files = {
        "a.csv": "id,name\n1,a\n",
        "b.csv": "id,age\n2,3\n",
        "c.csv": "zip\n99\n",
    }
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert r.rows()[0] == ["age", "id", "name", "zip"]


# --- Spec: "Column order: ascending lexicographic order of column names" ----
def test_lexicographic_column_order(tmp_path):
    files = {"a.csv": "b,C,a,_z,10\n1,2,3,4,5\n"}
    r = merge(tmp_path, files, "--key", "a")
    assert r.ok, r
    assert r.rows()[0] == sorted(["b", "C", "a", "_z", "10"])


# --- Spec: "`strict` (default): infer types based on observed values" -------
def test_strict_is_the_default(tmp_path):
    files = {"a.csv": "id\n10\n9\n"}
    default = merge(tmp_path, files, "--key", "id")
    explicit = merge(tmp_path, files, "--key", "id", "--infer", "strict")
    assert default.ok and explicit.ok
    assert default.stdout == explicit.stdout


# --- Spec: "`strict`: infer types based on observed values" (int inferred) --
def test_strict_infers_int(tmp_path):
    files = {"a.csv": "id\n10\n9\n100\n"}
    r = merge(tmp_path, files, "--key", "id", "--infer", "strict")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["9", "10", "100"]


# --- Spec: "columns with conflicting types across files fall back to string"
def test_strict_conflicting_types_across_files(tmp_path):
    files = {
        "a.csv": "k\n10\n",
        "b.csv": "k\nxyz\n",
    }
    r = merge(tmp_path, files, "--key", "k", "--infer", "strict")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["10", "xyz"]


# --- Spec: "columns with conflicting types across files fall back to string"
#           - int in one file, float in another (see AMBIGUITIES T1) --------
def test_strict_int_vs_float_across_files_is_string(tmp_path):
    files = {
        "a.csv": "k\n3\n",
        "b.csv": "k\n2.50\n",
    }
    r = merge(tmp_path, files, "--key", "k", "--infer", "strict")
    assert r.ok, r
    # `string` => values pass through verbatim, no float normalization
    assert sorted(x[0] for x in r.rows()[1:]) == ["2.50", "3"]


# --- Spec: strict, no conflict => the shared type is used -------------------
def test_strict_agreeing_types_across_files(tmp_path):
    files = {
        "a.csv": "k\n3\n",
        "b.csv": "k\n20\n",
    }
    r = merge(tmp_path, files, "--key", "k", "--infer", "strict")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["3", "20"]  # numeric, not "20" < "3"


# --- Spec: "`loose`: prefer numeric/temporal types if all non-null observed
#            values parse" -------------------------------------------------
def test_loose_prefers_numeric(tmp_path):
    files = {
        "a.csv": "k\n3\n",
        "b.csv": "k\n2.5\n",
    }
    r = merge(tmp_path, files, "--key", "k", "--infer", "loose")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["2.5", "3.0"]


# --- Spec: "`loose`: ... otherwise fall back to `string`" -------------------
def test_loose_falls_back_to_string(tmp_path):
    files = {"a.csv": "k\n3\nabc\n"}
    r = merge(tmp_path, files, "--key", "k", "--infer", "loose")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["3", "abc"]


# --- Spec: "`loose`: ... empty strings are treated as nulls and don't affect
#            inference" ----------------------------------------------------
def test_loose_ignores_empty_strings(tmp_path):
    files = {"a.csv": "id,k\n1,10\n2,\n3,9\n"}
    r = merge(tmp_path, files, "--key", "k", "--infer", "loose")
    assert r.ok, r
    # int inferred despite the empty cell; the null sorts first
    assert r.rows()[1:] == [["2", ""], ["3", "9"], ["1", "10"]]


# --- Spec: strict vs loose differ on empty cells (see AMBIGUITIES T1) ------
def test_strict_empty_cell_forces_string(tmp_path):
    files = {"a.csv": "id,k\n1,10\n2,\n3,9\n"}
    r = merge(tmp_path, files, "--key", "k", "--infer", "strict")
    assert r.ok, r
    # `k` falls back to string, so the order is lexicographic
    assert r.rows()[1:] == [["2", ""], ["1", "10"], ["3", "9"]]


# --- Spec: "`loose`: prefer numeric/temporal types" - temporal case ---------
def test_loose_infers_temporal(tmp_path):
    files = {"a.csv": "d\n2024-03-01\n2023-12-31\n"}
    r = merge(tmp_path, files, "--key", "d", "--infer", "loose")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["2023-12-31", "2024-03-01"]


def test_loose_infers_timestamp(tmp_path):
    files = {"a.csv": "t\n2024-03-01T05:00:00+02:00\n2024-03-01T01:00:00Z\n"}
    r = merge(tmp_path, files, "--key", "t", "--infer", "loose")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == [
        "2024-03-01T01:00:00Z",
        "2024-03-01T03:00:00Z",
    ]


# --- Spec: "Type priority: timestamp > date > bool > int > float > string"
#           - int wins over float when every value is integral --------------
def test_priority_int_over_float(tmp_path):
    files = {"a.csv": "k\n1\n2\n"}
    r = merge(tmp_path, files, "--key", "k", "--infer", "loose")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["1", "2"]  # not 1.0 / 2.0


# --- Spec: "Type priority: ... bool > int ..." - 1/0 columns are bool -------
def test_priority_bool_over_int(tmp_path):
    files = {"a.csv": "k\n1\n0\n"}
    r = merge(tmp_path, files, "--key", "k", "--infer", "loose")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["false", "true"]


# --- Spec: "`loose`: ... otherwise fall back to `string`" - one unparseable
#           value demotes the whole column ---------------------------------
def test_loose_one_bad_date_demotes_column_to_string(tmp_path):
    files = {"a.csv": "k\n2024-01-01\nnot-a-date\n"}
    r = merge(tmp_path, files, "--key", "k", "--infer", "loose")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["2024-01-01", "not-a-date"]


# --- Spec ambiguity T3: date-only values do not infer as timestamp ---------
def test_date_only_column_infers_date_not_timestamp(tmp_path):
    files = {"a.csv": "k\n2024-01-01\n"}
    r = merge(tmp_path, files, "--key", "k", "--infer", "loose")
    assert r.ok, r
    assert r.rows()[1] == ["2024-01-01"]


# --- Spec ambiguity T11: a column absent from a file is not an observed value
def test_absent_column_does_not_affect_inference(tmp_path):
    files = {
        "a.csv": "id\n1\n",
        "b.csv": "id,n\n2,10\n",
        "c.csv": "id,n\n3,9\n",
    }
    r = merge(tmp_path, files, "--key", "n")
    assert r.ok, r
    # n stays int (numeric ordering), row from a.csv is null => first
    assert [x[0] for x in r.rows()[1:]] == ["1", "3", "2"]


# --- Spec: "Missing columns in a file filled with null literal" ------------
def test_missing_columns_filled(tmp_path):
    files = {
        "a.csv": "a\n5\n",
        "b.csv": "b\nx\n",
    }
    r = merge(tmp_path, files, "--key", "a", "--csv-null-literal", "?")
    assert r.ok, r
    assert r.rows() == [["a", "b"], ["?", "x"], ["5", "?"]]
