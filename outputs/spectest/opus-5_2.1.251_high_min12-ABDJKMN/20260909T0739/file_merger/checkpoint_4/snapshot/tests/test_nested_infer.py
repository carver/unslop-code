"""Checkpoint 5: schema inference stays flat-only; error 6 without --schema."""
from conftest import (cell, cells, merge, merge_paths, nested_schema,
                      pa_modules, struct_of, write, write_jsonl, write_parquet,
                      write_tsv)


# --- Spec: "Without --schema: Reject inputs containing nested objects/arrays
#            in JSONL/Parquet. Error: ERR 6 nested structure requires provided
#            --schema (exit 6)" -------------------------------------------
def test_jsonl_object_without_schema_is_error_6(tmp_path):
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    r = merge_paths([src], "--key", "id")
    assert r.returncode == 6, r
    assert r.stderr.startswith("ERR 6 "), r.stderr
    assert "nested structure requires provided --schema" in r.stderr


def test_jsonl_array_without_schema_is_error_6(tmp_path):
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [1, 2]}])
    r = merge_paths([src], "--key", "id")
    assert r.returncode == 6, r


def test_parquet_nested_without_schema_is_error_6(tmp_path):
    pa, _pq = pa_modules()
    schema_pa = pa.schema([
        pa.field("id", pa.int64()),
        pa.field("u", pa.struct([pa.field("a", pa.int64())])),
    ])
    src = write_parquet(tmp_path, "a.parquet", [{"id": 1, "u": {"a": 1}}],
                        schema=schema_pa)
    r = merge_paths([src], "--key", "id")
    assert r.returncode == 6, r
    assert "nested structure requires provided --schema" in r.stderr


# --- Spec: "Inferred columns remain flat" --------------------------------
def test_inference_still_produces_flat_columns(tmp_path):
    files = {"a.csv": "id,v\n1,2\n", "b.jsonl": '{"id": 2, "v": 3}\n'}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert r.rows()[0] == ["id", "v"]


# --- Spec: "CSV/TSV cells containing JSON treated as string" -------------
def test_csv_json_cell_is_a_string_when_inferring(tmp_path):
    files = {"a.csv": 'id,v\n1,"{""a"": 1}"\n'}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert cell(r, 0, "v") == '{"a": 1}'


def test_tsv_json_cell_is_a_string_when_inferring(tmp_path):
    src = write_tsv(tmp_path, "a.tsv", [["id", "v"], ["1", '[1, 2]']])
    r = merge_paths([src], "--key", "id")
    assert r.ok, r
    assert cell(r, 0, "v") == "[1, 2]"


# --- Spec: "Without --schema, nested inputs not allowed (error 6)" -------
def test_error_6_even_when_the_nested_column_is_not_a_key(tmp_path):
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "other": {"a": 1}}])
    r = merge_paths([src], "--key", "id")
    assert r.returncode == 6, r


def test_flat_jsonl_without_schema_still_works(tmp_path):
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 2, "v": "b"}, {"id": 1, "v": "a"}])
    r = merge_paths([src], "--key", "id")
    assert r.ok, r
    assert cells(r, "id") == ["1", "2"]


# --- Spec: "Schema Inference (Unchanged, Flat-Only)" - --infer/--schema-
#           strategy behaviour is untouched ------------------------------
def test_infer_flags_still_accepted(tmp_path):
    files = {"a.csv": "id,v\n1,2\n", "b.csv": "id,v\n2,2.5\n"}
    r = merge(tmp_path, files, "--key", "id", "--infer", "loose",
              "--schema-strategy", "union")
    assert r.ok, r
    assert cells(r, "v") == ["2.0", "2.5"]
