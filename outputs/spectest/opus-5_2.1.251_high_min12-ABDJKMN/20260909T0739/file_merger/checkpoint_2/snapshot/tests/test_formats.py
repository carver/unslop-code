"""`New Input Types`: per-file format detection (`--input-format`)."""
from conftest import (merge_paths, run, write, write_bytes, write_gz,
                      write_jsonl, write_jsonl_gz, write_parquet, write_tsv)


# --- Spec: "--input-format=auto (default): detect per file by extension and
#            magic bytes: `.csv` -> csv" ------------------------------------
def test_auto_detects_csv_by_extension(tmp_path):
    a = write(tmp_path, "a.csv", "id,name\n7,x\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["7", "x"]]


# --- Spec: "`.tsv` -> tsv" -------------------------------------------------
def test_auto_detects_tsv_by_extension(tmp_path):
    a = write_tsv(tmp_path, "a.tsv", [["id", "name"], ["7", "x,y"]])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    # A comma is data in a TSV source and must be quoted on output.
    assert r.rows() == [["id", "name"], ["7", "x,y"]]


# --- Spec: "`.jsonl`/`.ndjson` -> jsonl" -----------------------------------
def test_auto_detects_jsonl_by_extension(tmp_path):
    a = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "name": "x"}])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["1", "x"]]


def test_auto_detects_ndjson_by_extension(tmp_path):
    a = write_jsonl(tmp_path, "a.ndjson", [{"id": 2, "name": "y"}])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["2", "y"]]


# --- Spec: "`.parquet` -> parquet" -----------------------------------------
def test_auto_detects_parquet_by_extension(tmp_path):
    a = write_parquet(tmp_path, "a.parquet", [{"id": 1, "name": "x"}])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["1", "x"]]


# --- Spec: "For gzip, allow `.gz` suffix after base extension (e.g.,
#            `data.csv.gz`, `events.jsonl.gz`)" -----------------------------
def test_auto_detects_csv_gz(tmp_path):
    a = write_gz(tmp_path, "data.csv.gz", "id,name\n7,x\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["7", "x"]]


def test_auto_detects_jsonl_gz(tmp_path):
    a = write_jsonl_gz(tmp_path, "events.jsonl.gz", [{"id": 3, "name": "z"}])
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["3", "z"]]


def test_auto_detects_tsv_gz(tmp_path):
    a = write_gz(tmp_path, "t.tsv.gz", "id\tname\n7\tx\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["7", "x"]]


# --- Spec: "If extension is ambiguous and magic bytes indicate Parquet,
#            treat as parquet" ---------------------------------------------
def test_unknown_extension_with_parquet_magic_is_parquet(tmp_path):
    src = write_parquet(tmp_path, "src.parquet", [{"id": 5, "name": "q"}])
    blob = write_bytes(tmp_path, "mystery.dat", src.read_bytes())
    r = merge_paths([blob], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["5", "q"]]


def test_no_extension_with_parquet_magic_is_parquet(tmp_path):
    src = write_parquet(tmp_path, "src.parquet", [{"id": 6, "name": "w"}])
    blob = write_bytes(tmp_path, "noext", src.read_bytes())
    r = merge_paths([blob], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["6", "w"]


# --- Spec: "... otherwise error 2" -----------------------------------------
def test_ambiguous_extension_without_parquet_magic_is_error_2(tmp_path):
    a = write(tmp_path, "a.dat", "id,name\n1,x\n")
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 2, r
    assert r.stderr.strip()


def test_extensionless_text_file_is_error_2(tmp_path):
    a = write(tmp_path, "plain", "id,name\n1,x\n")
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 2, r


# --- Spec: "--input-format {auto,csv,tsv,jsonl,parquet}" - an explicit
#            format overrides extension-based detection --------------------
def test_explicit_format_overrides_extension(tmp_path):
    a = write(tmp_path, "a.dat", "id,name\n7,x\n")
    r = merge_paths([a], "--key", "id", "--input-format", "csv")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["7", "x"]]


def test_explicit_jsonl_format_on_odd_extension(tmp_path):
    a = write(tmp_path, "a.log", '{"id": 7, "v": "a"}\n')
    r = merge_paths([a], "--key", "id", "--input-format", "jsonl")
    assert r.ok, r
    assert r.rows() == [["id", "v"], ["7", "a"]]


def test_explicit_tsv_format_applies_to_all_inputs(tmp_path):
    a = write(tmp_path, "a.txt", "id\tname\n1\tx\n")
    b = write(tmp_path, "b.txt", "id\tname\n2\ty\n")
    r = merge_paths([a, b], "--key", "id", "--input-format", "tsv")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["1", "x"], ["2", "y"]]


# --- Spec: "Accepted file types: CSV, TSV, JSON Lines (NDJSON), Parquet" ---
def test_all_four_formats_in_one_run(tmp_path):
    c = write(tmp_path, "a.csv", "id,name\n1,c\n")
    t = write_tsv(tmp_path, "b.tsv", [["id", "name"], ["2", "t"]])
    j = write_jsonl(tmp_path, "c.jsonl", [{"id": 3, "name": "j"}])
    p = write_parquet(tmp_path, "d.parquet", [{"id": 4, "name": "p"}])
    r = merge_paths([c, t, j, p], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["1", "c"], ["2", "t"],
                        ["3", "j"], ["4", "p"]]
