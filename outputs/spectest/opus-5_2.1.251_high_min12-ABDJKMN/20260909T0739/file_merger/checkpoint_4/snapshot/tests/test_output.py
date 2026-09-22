"""The `Output` section of the spec."""
import csv
import io
from pathlib import Path

from conftest import merge, parse_csv, run, write, write_schema


# --- Spec: "Single CSV with header row and all rows from inputs" -------------
def test_header_plus_all_rows(tmp_path):
    files = {
        "a.csv": "id,name\n2,b\n1,a\n",
        "b.csv": "id,name\n3,c\n",
    }
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    rows = r.rows()
    assert rows[0] == ["id", "name"]
    assert len(rows) == 4  # header + 3 data rows


# --- Spec: "sorted globally by the key(s)" (across files, not per file) ------
def test_rows_sorted_globally_across_files(tmp_path):
    files = {
        "a.csv": "id\n1\n4\n",
        "b.csv": "id\n2\n3\n",
    }
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert [row[0] for row in r.rows()[1:]] == ["1", "2", "3", "4"]


# --- Spec: "If `--output -`: write to stdout" -------------------------------
def test_output_dash_writes_to_stdout(tmp_path):
    a = write(tmp_path, "a.csv", "id\n7\n")
    r = run("--output", "-", "--key", "id", a)
    assert r.ok, r
    assert r.stdout == "id\n7\n"


# --- Spec: "otherwise write to file path" -----------------------------------
def test_output_path_writes_file(tmp_path):
    a = write(tmp_path, "a.csv", "id\n9\n2\n")
    out = tmp_path / "merged.csv"
    r = run("--output", out, "--key", "id", a)
    assert r.ok, r
    assert r.stdout == ""
    assert out.read_text(encoding="utf-8") == "id\n2\n9\n"


# --- Spec: "Columns in output header must match the resolved schema order" ---
def test_header_matches_schema_order(tmp_path):
    schema = write_schema(
        tmp_path, "s.json", [("id", "int"), ("ts", "timestamp"), ("note", "string")]
    )
    files = {"a.csv": "note,id,ts\nhi,1,2024-07-01T00:00:00Z\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[0] == ["id", "ts", "note"]
    assert r.rows()[1] == ["1", "2024-07-01T00:00:00Z", "hi"]


# --- Spec: "Columns in output header must match the resolved schema order"
#           (inferred schema => lexicographic order) -------------------------
def test_header_matches_inferred_order(tmp_path):
    files = {"a.csv": "zeta,alpha,Mid\n1,2,3\n"}
    r = merge(tmp_path, files, "--key", "alpha")
    assert r.ok, r
    assert r.rows()[0] == ["Mid", "alpha", "zeta"]


# --- Spec: "Missing values emitted as the null literal (default empty string)"
def test_missing_values_default_to_empty_string(tmp_path):
    files = {
        "a.csv": "id,name\n1,a\n",
        "b.csv": "id,extra\n2,x\n",
    }
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    rows = r.rows()
    assert rows[0] == ["extra", "id", "name"]
    assert rows[1] == ["", "1", "a"]
    assert rows[2] == ["x", "2", ""]


# --- Spec: "override with `--csv-null-literal`" -----------------------------
def test_null_literal_override(tmp_path):
    files = {
        "a.csv": "id,name\n1,a\n",
        "b.csv": "id,extra\n2,x\n",
    }
    r = merge(tmp_path, files, "--key", "id", "--csv-null-literal", "NULL")
    assert r.ok, r
    rows = r.rows()
    assert rows[1] == ["NULL", "1", "a"]
    assert rows[2] == ["x", "2", "NULL"]


# --- Spec: "Missing values emitted as the null literal" - an empty cell is a
#           missing value too (see AMBIGUITIES T18) --------------------------
def test_empty_cell_uses_null_literal(tmp_path):
    files = {"a.csv": "id,note\n7,\n"}
    r = merge(tmp_path, files, "--key", "id", "--csv-null-literal", "NULL")
    assert r.ok, r
    assert r.rows()[1] == ["7", "NULL"]


# --- Spec: header row is written even with no data rows ---------------------
def test_header_only_inputs_still_emit_header(tmp_path):
    files = {"a.csv": "id,name\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert r.stdout == "id,name\n"


# --- Spec: "all rows from inputs" - duplicates are preserved, not deduped ----
def test_duplicate_rows_are_all_kept(tmp_path):
    files = {"a.csv": "id\n7\n7\n7\n", "b.csv": "id\n7\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert len(r.rows()) == 5
