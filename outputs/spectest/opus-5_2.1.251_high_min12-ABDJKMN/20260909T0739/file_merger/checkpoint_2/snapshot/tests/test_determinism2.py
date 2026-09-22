"""The multi-format `Determinism Checklist`."""
from conftest import merge_paths, write, write_jsonl, write_parquet


# --- Spec: "Input format detection and gzip handling follow rules above" --
def test_repeated_runs_are_byte_identical(tmp_path):
    c = write(tmp_path, "a.csv", "id,v\n2,b\n1,a\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 3, "v": "c"}])
    p = write_parquet(tmp_path, "c.parquet", [{"id": 0, "v": "z"}])
    first = merge_paths([c, j, p], "--key", "id")
    second = merge_paths([c, j, p], "--key", "id")
    assert first.ok and second.ok
    assert first.stdout == second.stdout


# --- Spec: "Schema resolution honors chosen --schema-strategy; column order
#            is lexicographic when inferred" ------------------------------
def test_column_order_independent_of_input_order(tmp_path):
    c = write(tmp_path, "a.csv", "b,a\n1,2\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"c": 3, "a": 4}])
    one = merge_paths([c, j], "--key", "a")
    two = merge_paths([j, c], "--key", "a")
    assert one.ok and two.ok
    assert one.rows()[0] == two.rows()[0] == ["a", "b", "c"]


# --- Spec: "Exact exit codes and stderr message shape as specified" -------
def test_errors_go_to_stderr_and_stdout_stays_clean(tmp_path):
    j = write(tmp_path, "a.jsonl", '{"id": 1, "n": {"k": 2}}\n')
    r = merge_paths([j], "--key", "id")
    assert r.returncode == 6, r
    assert r.stdout == ""
    assert r.stderr.startswith("merge_files.py: error: ")
    assert r.stderr.endswith("\n")


def test_distinct_error_classes_use_distinct_codes(tmp_path):
    plain = write(tmp_path, "a.dat", "id\n1\n")
    ok_csv = write(tmp_path, "b.csv", "id\n1\n")
    nested = write(tmp_path, "c.jsonl", '{"id": 1, "n": []}\n')
    codes = {
        "format": merge_paths([plain], "--key", "id").returncode,
        "key": merge_paths([ok_csv], "--key", "absent").returncode,
        "nested": merge_paths([nested], "--key", "id").returncode,
    }
    assert codes == {"format": 2, "key": 3, "nested": 6}


# --- Spec: "All values cast per final schema; nulls/missing rendered as
#            configured null literal" -------------------------------------
def test_nulls_from_every_source_share_one_rendering(tmp_path):
    c = write(tmp_path, "a.csv", "id,v\n1,\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2}])
    p = write_parquet(tmp_path, "c.parquet", [{"id": 3, "v": None}])
    r = merge_paths([c, j, p], "--key", "id", "--csv-null-literal", "NULL")
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["NULL"] * 3


# --- Spec: "Sort correctness and stability across mixed sources" ----------
def test_sort_and_stability_checklist(tmp_path):
    c = write(tmp_path, "a.csv", "id,src\n2,csv2\n1,csv1\n")
    j = write_jsonl(tmp_path, "b.jsonl",
                    [{"id": 1, "src": "jsonl1"}, {"id": 2, "src": "jsonl2"}])
    r = merge_paths([c, j], "--key", "id")
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["csv1", "jsonl1",
                                                "csv2", "jsonl2"]
