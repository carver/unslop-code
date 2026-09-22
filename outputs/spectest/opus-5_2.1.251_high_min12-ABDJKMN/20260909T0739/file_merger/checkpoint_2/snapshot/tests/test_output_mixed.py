"""`Output` for heterogeneous merges."""
import os

from conftest import (merge_paths, run, write, write_jsonl, write_parquet,
                      write_schema, write_tsv)


# --- Spec: "Always produce single CSV with header row in resolved column
#            order" -------------------------------------------------------
def test_single_csv_with_header_in_resolved_order(tmp_path):
    j = write_jsonl(tmp_path, "a.jsonl", [{"b": 1, "a": 2}])
    p = write_parquet(tmp_path, "b.parquet", [{"c": 3, "a": 4}])
    r = merge_paths([j, p], "--key", "a")
    assert r.ok, r
    assert r.rows()[0] == ["a", "b", "c"]


def test_header_follows_provided_schema_order(tmp_path):
    schema = write_schema(tmp_path, "s.json",
                          [("z", "int"), ("a", "int")])
    j = write_jsonl(tmp_path, "a.jsonl", [{"a": 1, "z": 2}])
    r = merge_paths([j], "--key", "a", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[0] == ["z", "a"]


# --- Spec: "All rows from all inputs appear exactly once; no
#            deduplication" ----------------------------------------------
def test_identical_rows_from_different_formats_are_all_kept(tmp_path):
    c = write(tmp_path, "a.csv", "id,v\n1,x\n1,x\n")
    t = write_tsv(tmp_path, "b.tsv", [["id", "v"], ["1", "x"]])
    j = write_jsonl(tmp_path, "c.jsonl", [{"id": 1, "v": "x"}])
    p = write_parquet(tmp_path, "d.parquet", [{"id": 1, "v": "x"}])
    r = merge_paths([c, t, j, p], "--key", "id")
    assert r.ok, r
    assert len(r.rows()) == 6
    assert all(row == ["1", "x"] for row in r.rows()[1:])


# --- Spec: "--output - writes to stdout" ----------------------------------
def test_output_dash_writes_to_stdout(tmp_path):
    j = write_jsonl(tmp_path, "a.jsonl", [{"id": 1}])
    r = run("--output", "-", "--key", "id", str(j), cwd=tmp_path)
    assert r.ok, r
    assert r.stdout == "id\n1\n"


# --- Spec: "otherwise write atomically" -----------------------------------
def test_file_output_is_written(tmp_path):
    j = write_jsonl(tmp_path, "a.jsonl", [{"id": 2}, {"id": 1}])
    out = tmp_path / "merged.csv"
    r = run("--output", str(out), "--key", "id", str(j), cwd=tmp_path)
    assert r.ok, r
    assert out.read_text(encoding="utf-8") == "id\n1\n2\n"


def test_failed_run_leaves_existing_output_untouched(tmp_path):
    out = tmp_path / "merged.csv"
    out.write_text("PREVIOUS\n", encoding="utf-8")
    bad = write(tmp_path, "a.jsonl", '{"id": 1, "nested": {"k": 1}}\n')
    r = run("--output", str(out), "--key", "id", str(bad), cwd=tmp_path)
    assert r.returncode == 6, r
    assert out.read_text(encoding="utf-8") == "PREVIOUS\n"


def test_no_temporary_files_left_behind(tmp_path):
    outdir = tmp_path / "out"
    outdir.mkdir()
    j = write_jsonl(tmp_path, "a.jsonl", [{"id": 1}])
    out = outdir / "merged.csv"
    r = run("--output", str(out), "--key", "id", str(j), cwd=tmp_path)
    assert r.ok, r
    assert sorted(os.listdir(outdir)) == ["merged.csv"]


# --- Spec: "Use configured CSV dialect flags for output quoting/escaping
#            and chosen null literal" -------------------------------------
def test_output_uses_configured_null_literal(tmp_path):
    j = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": None}])
    r = merge_paths([j], "--key", "id", "--csv-null-literal", "\\N")
    assert r.ok, r
    assert r.stdout == "id,v\n1,\\N\n"


def test_output_uses_configured_quotechar(tmp_path):
    j = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": "a,b"}])
    r = merge_paths([j], "--key", "id", "--csv-quotechar", "|")
    assert r.ok, r
    assert r.stdout == "id,v\n1,|a,b|\n"


def test_output_uses_configured_escapechar(tmp_path):
    j = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": 'a"b'}])
    r = merge_paths([j], "--key", "id", "--csv-escapechar", "\\")
    assert r.ok, r
    assert r.stdout == 'id,v\n1,a\\"b\n'


# --- Spec: "Always produce single CSV with header row" - even when every
#            input is empty of rows ---------------------------------------
def test_header_only_output_when_no_rows(tmp_path):
    j = write(tmp_path, "a.jsonl", "")
    c = write(tmp_path, "b.csv", "id,v\n")
    r = merge_paths([j, c], "--key", "id")
    assert r.ok, r
    assert r.stdout == "id,v\n"
