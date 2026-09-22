"""Spec sections: Sorting and Stability, Output, Performance & Memory."""

import csv
import io
import json
import os

from conftest import (body, col, header, lines, pa, read_text, run, run_ok,
                      rows_of, write, write_jsonl, write_parquet, write_schema,
                      write_tsv)


# --- Spec: "Sorting by `--key` uses casted key values" ---
# Context: Sorting and Stability; numeric keys order numerically across formats.
def test_sort_uses_casted_key_values_across_formats(ws):
    a = write(ws / "a.csv", "id\n10\n")
    b = write_jsonl(ws / "b.jsonl", [{"id": 9}])
    c = write_parquet(ws / "c.parquet", {"id": [100]})
    res = run_ok("--output", "-", "--key", "id", a, b, c)
    assert col(res.stdout, "id") == ["9", "10", "100"]


# --- Spec: "Keys must exist in resolved schema (error 3 otherwise)" ---
# Context: Sorting and Stability.
def test_missing_key_column_is_error_3(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1}])
    res = run("--output", "-", "--key", "nope", a)
    assert res.returncode == 3
    assert res.stderr.strip() != ""


# --- Spec: "Keys must exist in resolved schema (error 3 otherwise)" ---
# Context: Sorting; the schema, not the inputs, is the criterion.
def test_key_absent_from_provided_schema_is_error_3(ws):
    a = write(ws / "a.csv", "id,v\n1,x\n")
    s = write_schema(ws / "s.json", [("v", "string")])
    res = run("--output", "-", "--key", "id", "--schema", s, a)
    assert res.returncode == 3


# --- Spec: "Keys must exist in resolved schema" ---
# Context: Sorting; one bad key in a composite key is still error 3.
def test_one_bad_key_in_composite_is_error_3(ws):
    a = write(ws / "a.csv", "id,v\n1,x\n")
    res = run("--output", "-", "--key", "id,ghost", a)
    assert res.returncode == 3


# --- Spec: "Sort must be stable for equal keys" ---
# Context: Sorting and Stability; ties keep input order, file by file.
def test_stability_across_mixed_sources(ws):
    a = write(ws / "a.csv", "k,tag\n1,a1\n1,a2\n")
    b = write_jsonl(ws / "b.jsonl", [{"k": 1, "tag": "b1"}, {"k": 1, "tag": "b2"}])
    c = write_parquet(ws / "c.parquet", {"k": [1, 1], "tag": ["c1", "c2"]})
    res = run_ok("--output", "-", "--key", "k", a, b, c)
    assert col(res.stdout, "tag") == ["a1", "a2", "b1", "b2", "c1", "c2"]


# --- Spec: "Sort must be stable for equal keys" under --desc ---
# Context: Sorting and Stability; the tie-break stays in input order.
def test_stability_under_desc_across_mixed_sources(ws):
    a = write(ws / "a.csv", "k,tag\n1,a1\n1,a2\n")
    b = write_jsonl(ws / "b.jsonl", [{"k": 1, "tag": "b1"}])
    res = run_ok("--output", "-", "--key", "k", "--desc", a, b)
    assert col(res.stdout, "tag") == ["a1", "a2", "b1"]


# --- Spec: "--key <col>[,<col>...]" composite sort across formats ---
# Context: Sorting and Stability; the documented consensus example shape.
def test_composite_key_across_formats(ws):
    a = write(ws / "a.csv", "ts,id\n2024-01-02,2\n2024-01-01,5\n")
    b = write_jsonl(ws / "b.jsonl", [{"ts": "2024-01-01", "id": 1}])
    res = run_ok("--output", "-", "--key", "ts,id", a, b)
    # Inferred column order is lexicographic, so `id` precedes `ts`.
    assert header(res.stdout) == ["id", "ts"]
    assert body(res.stdout) == ["1,2024-01-01", "5,2024-01-01", "2,2024-01-02"]


# --- Spec: "[--desc]" ---
# Context: Sorting and Stability; descending across formats.
def test_desc_across_formats(ws):
    a = write(ws / "a.csv", "id\n1\n")
    b = write_jsonl(ws / "b.jsonl", [{"id": 3}])
    c = write_parquet(ws / "c.parquet", {"id": [2]})
    res = run_ok("--output", "-", "--key", "id", "--desc", a, b, c)
    assert col(res.stdout, "id") == ["3", "2", "1"]


# --- Spec: "Always produce single CSV with header row in resolved column
#            order" ---
# Context: Output; the output is CSV even when no input was.
def test_output_is_csv_even_for_non_csv_inputs(ws):
    a = write_jsonl(ws / "a.jsonl", [{"b": 1, "a": "x,y"}])
    res = run_ok("--output", "-", "--key", "b", a)
    assert lines(res.stdout) == ['a,b', '"x,y",1']


# --- Spec: "All rows from all inputs appear exactly once; no deduplication" ---
# Context: Output.
def test_no_deduplication(ws):
    a = write(ws / "a.csv", "id,v\n1,x\n1,x\n")
    b = write_jsonl(ws / "b.jsonl", [{"id": 1, "v": "x"}])
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert body(res.stdout) == ["1,x"] * 3


# --- Spec: "`--output -` writes to stdout" ---
# Context: Output.
def test_output_dash_writes_stdout(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert res.stdout.startswith("id\n")


# --- Spec: "otherwise write atomically" ---
# Context: Output; the destination holds the complete file afterwards.
def test_output_file_written(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 2}, {"id": 1}])
    out = ws / "o.csv"
    run_ok("--output", str(out), "--key", "id", a)
    assert read_text(out) == "id\n1\n2\n"


# --- Spec: "otherwise write atomically" ---
# Context: Output; a failed run leaves the previous file untouched and drops no
# partial file or temp leftovers in the destination directory (see T40).
def test_atomic_write_leaves_previous_content_on_failure(ws):
    outdir = ws / "out"
    outdir.mkdir()
    out = outdir / "o.csv"
    write(out, "OLD\n")
    a = write(ws / "a.csv", "id,v\n1,bad\n")
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run("--output", str(out), "--key", "id", "--schema", s,
              "--on-type-error", "fail", a)
    assert res.returncode != 0
    assert read_text(out) == "OLD\n"
    assert os.listdir(outdir) == ["o.csv"]


# --- Spec: "otherwise write atomically" ---
# Context: Output; nothing is created when the run fails before writing.
def test_no_output_file_created_on_failure(ws):
    outdir = ws / "out"
    outdir.mkdir()
    out = outdir / "o.csv"
    a = write(ws / "a.jsonl", '{"id": 1, "bad": [1]}\n')
    res = run("--output", str(out), "--key", "id", a)
    assert res.returncode == 6
    assert os.listdir(outdir) == []


# --- Spec: "Use configured CSV dialect flags for output quoting/escaping and
#            chosen null literal" ---
# Context: Output; --csv-quotechar applies to the emitted CSV.
def test_output_uses_configured_quotechar(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": "x,y"}])
    res = run_ok("--output", "-", "--key", "id", "--csv-quotechar", "'", a)
    assert body(res.stdout) == ["1,'x,y'"]


# --- Spec: "and chosen null literal" ---
# Context: Output.
def test_output_uses_configured_null_literal(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "v": None}])
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "\\N", a)
    assert body(res.stdout) == ["1,\\N"]


# --- Spec: "Implementation must work with `--memory-limit-mb` as low as 64" ---
# Context: Performance & Memory; mixed sources spill and still sort.
def test_low_memory_limit_with_mixed_sources(ws):
    n = 4000
    write(ws / "a.csv", "id,pad\n" +
          "".join(f"{i},{'x' * 50}\n" for i in range(0, n, 2)))
    write_jsonl(ws / "b.jsonl",
                [{"id": i, "pad": "y" * 50} for i in range(1, n, 2)])
    res = run_ok("--output", "-", "--key", "id", "--memory-limit-mb", "1",
                 str(ws / "a.csv"), str(ws / "b.jsonl"))
    ids = [int(v) for v in col(res.stdout, "id")]
    assert ids == list(range(n))


# --- Spec: "Avoid format-specific issues (e.g., don't load entire Parquet
#            files ...)" ---
# Context: Performance & Memory; a many-row-group Parquet sorts under a tiny
# memory limit.
def test_parquet_streams_under_low_memory_limit(ws):
    n = 4000
    a = write_parquet(ws / "a.parquet",
                      {"id": list(range(n - 1, -1, -1)),
                       "pad": ["z" * 60] * n},
                      row_group_size=100)
    res = run_ok("--output", "-", "--key", "id", "--memory-limit-mb", "1",
                 "--parquet-row-group-bytes", "4096", a)
    ids = [int(v) for v in col(res.stdout, "id")]
    assert ids == list(range(n))


# --- Spec: "All intermediate resources must be cleaned up" (checkpoint 1) with
#            gzipped Parquet, which needs scratch space ---
# Context: Performance & Memory.
def test_temp_dir_emptied_after_gzipped_parquet_run(ws):
    from conftest import gzip_existing
    tmp = ws / "scratch"
    tmp.mkdir()
    src = write_parquet(ws / "src.parquet", {"id": [2, 1]})
    a = gzip_existing(src, ws / "m.parquet.gz")
    run_ok("--output", "-", "--key", "id", "--temp-dir", str(tmp), a)
    assert os.listdir(tmp) == []


# --- Spec: the documented mixed-format example invocation ---
# Context: Examples; CSV + gzipped JSONL + Parquet, consensus, composite key.
def test_documented_mixed_example(ws):
    from conftest import write_jsonl_gz
    users = write(ws / "users.csv", "ts,id,src\n2024-01-03,3,csv\n")
    events = write_jsonl_gz(ws / "events.jsonl.gz",
                            [{"ts": "2024-01-01", "id": 1, "src": "jsonl"}])
    metrics = write_parquet(ws / "metrics.parquet",
                            {"ts": ["2024-01-02"], "id": [2], "src": ["pq"]})
    out = ws / "merged.csv"
    run_ok("--output", str(out), "--key", "ts,id",
           "--schema-strategy", "consensus", users, events, metrics)
    text = read_text(out)
    assert header(text) == ["id", "src", "ts"]
    assert col(text, "src") == ["jsonl", "pq", "csv"]
