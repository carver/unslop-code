"""`Sorting and Stability` across heterogeneous sources."""
from conftest import (merge_paths, write, write_jsonl, write_parquet,
                      write_schema, write_tsv)


# --- Spec: "Sorting by --key uses casted key values" ----------------------
def test_sort_uses_casted_not_lexical_key_values(tmp_path):
    c = write(tmp_path, "a.csv", "id,src\n10,csv\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 9, "src": "jsonl"}])
    r = merge_paths([c, j], "--key", "id")
    assert r.ok, r
    assert [row[0] for row in r.rows()[1:]] == ["9", "10"]


def test_sort_uses_casted_timestamps_across_formats(tmp_path):
    schema = write_schema(tmp_path, "s.json",
                          [("ts", "timestamp"), ("src", "string")])
    c = write(tmp_path, "a.csv", "ts,src\n2024-07-01T12:00:00+02:00,csv\n")
    j = write_jsonl(tmp_path, "b.jsonl",
                    [{"ts": "2024-07-01T11:00:00Z", "src": "jsonl"}])
    r = merge_paths([c, j], "--key", "ts", "--schema", str(schema))
    assert r.ok, r
    # csv row is 10:00Z after normalisation, so it sorts first.
    assert [row[1] for row in r.rows()[1:]] == ["csv", "jsonl"]


# --- Spec: "Keys must exist in resolved schema (error 3 otherwise)" -------
def test_missing_key_column_is_error_3(tmp_path):
    j = write_jsonl(tmp_path, "a.jsonl", [{"id": 1}])
    r = merge_paths([j], "--key", "nope")
    assert r.returncode == 3, r
    assert r.stderr.strip()


def test_key_absent_from_provided_schema_is_error_3(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int")])
    c = write(tmp_path, "a.csv", "id,ts\n1,2024-01-01\n")
    r = merge_paths([c], "--key", "ts", "--schema", str(schema))
    assert r.returncode == 3, r


def test_key_present_in_only_one_input_is_fine(tmp_path):
    c = write(tmp_path, "a.csv", "id\n1\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "k": 5}])
    r = merge_paths([c, j], "--key", "k")
    assert r.ok, r


# --- Spec: "Sort must be stable for equal keys" ---------------------------
def test_stability_across_mixed_sources(tmp_path):
    c = write(tmp_path, "a.csv", "id,src\n1,csv\n")
    t = write_tsv(tmp_path, "b.tsv", [["id", "src"], ["1", "tsv"]])
    j = write_jsonl(tmp_path, "c.jsonl", [{"id": 1, "src": "jsonl"}])
    p = write_parquet(tmp_path, "d.parquet", [{"id": 1, "src": "parquet"}])
    r = merge_paths([c, t, j, p], "--key", "id")
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["csv", "tsv", "jsonl", "parquet"]


def test_stability_holds_under_desc(tmp_path):
    c = write(tmp_path, "a.csv", "id,src\n1,csv\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 1, "src": "jsonl"}])
    r = merge_paths([c, j], "--key", "id", "--desc")
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["csv", "jsonl"]


# --- Spec: "--key <col>[,<col>...]" - composite keys over mixed sources ---
def test_composite_key_across_formats(tmp_path):
    c = write(tmp_path, "a.csv", "ts,id\n2024-01-02,2\n2024-01-01,5\n")
    j = write_jsonl(tmp_path, "b.jsonl",
                    [{"ts": "2024-01-01", "id": 1}])
    r = merge_paths([c, j], "--key", "ts,id")
    assert r.ok, r
    assert [row[0] for row in r.rows()[1:]] == ["1", "5", "2"]


# --- Spec: "[--desc]" - descending applies to the whole composite key -----
def test_desc_over_mixed_sources(tmp_path):
    c = write(tmp_path, "a.csv", "id\n1\n3\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2}])
    r = merge_paths([c, j], "--key", "id", "--desc")
    assert r.ok, r
    assert [row[0] for row in r.rows()[1:]] == ["3", "2", "1"]
