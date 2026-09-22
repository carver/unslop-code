"""Spec section: New Input Types — per-file format and compression detection."""

import gzip

from conftest import (body, col, header, gzip_existing, run, run_ok, write,
                      write_bytes, write_gz, write_jsonl, write_jsonl_gz,
                      write_parquet, write_tsv)


# --- Spec: "`--input-format=auto` (default): detect per file by extension ...
#            `.csv` → csv" ---
# Context: New Input Types. A .csv file keeps checkpoint-1 CSV semantics.
def test_auto_detects_csv_by_extension(ws):
    a = write(ws / "a.csv", 'id,note\n2,"x,y"\n1,z\n')
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["id", "note"]
    assert body(res.stdout) == ['1,z', '2,"x,y"']


# --- Spec: "`.tsv` → tsv" ---
# Context: New Input Types, extension table.
def test_auto_detects_tsv_by_extension(ws):
    a = write_tsv(ws / "a.tsv", ["id", "name"], [["2", "bee"], ["1", "ant"]])
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["id", "name"]
    assert body(res.stdout) == ["1,ant", "2,bee"]


# --- Spec: "`.jsonl`/`.ndjson` → jsonl" ---
# Context: New Input Types, extension table.
def test_auto_detects_jsonl_by_extension(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 2, "n": "b"}, {"id": 1, "n": "a"}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["id", "n"]
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "`.jsonl`/`.ndjson` → jsonl" ---
# Context: New Input Types; .ndjson is the same format.
def test_auto_detects_ndjson_by_extension(ws):
    a = write_jsonl(ws / "a.ndjson", [{"id": 2}, {"id": 1}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1", "2"]


# --- Spec: "`.parquet` → parquet" ---
# Context: New Input Types, extension table.
def test_auto_detects_parquet_by_extension(ws):
    a = write_parquet(ws / "a.parquet", {"id": [2, 1], "n": ["b", "a"]})
    res = run_ok("--output", "-", "--key", "id", a)
    assert header(res.stdout) == ["id", "n"]
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "For gzip, allow `.gz` suffix after base extension (e.g., `data.csv.gz`)" ---
# Context: New Input Types; the base extension still chooses the format.
def test_auto_detects_gzipped_csv(ws):
    a = write_gz(ws / "data.csv.gz", "id,v\n2,b\n1,a\n")
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "e.g., ... `events.jsonl.gz`" ---
# Context: New Input Types, gzip suffix after base extension.
def test_auto_detects_gzipped_jsonl(ws):
    a = write_jsonl_gz(ws / "events.jsonl.gz", [{"id": 2}, {"id": 1}])
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1", "2"]


# --- Spec: "For gzip, allow `.gz` suffix after base extension" ---
# Context: New Input Types; the rule is general, so .tsv.gz works too.
def test_auto_detects_gzipped_tsv(ws):
    plain = write_tsv(ws / "a.tsv", ["id", "v"], [["2", "b"], ["1", "a"]])
    a = gzip_existing(plain, ws / "b.tsv.gz")
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "If extension is ambiguous and magic bytes indicate Parquet, treat
#            as parquet" ---
# Context: New Input Types; an unknown extension over Parquet bytes.
def test_ambiguous_extension_with_parquet_magic_is_parquet(ws):
    src = write_parquet(ws / "src.parquet", {"id": [2, 1]})
    data = open(src, "rb").read()
    a = write_bytes(ws / "mystery.dat", data)
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1", "2"]


# --- Spec: "If extension is ambiguous ... otherwise error 2" ---
# Context: New Input Types; unknown extension, non-Parquet content.
def test_ambiguous_extension_without_parquet_magic_is_error_2(ws):
    a = write(ws / "mystery.dat", "id,v\n1,a\n")
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 2
    assert res.stderr.strip() != ""


# --- Spec: "If extension is ambiguous ... otherwise error 2" ---
# Context: New Input Types; a file with no extension at all is ambiguous.
def test_no_extension_without_magic_is_error_2(ws):
    a = write(ws / "plainfile", "id\n1\n")
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 2


# --- Spec: "detect per file by extension" ---
# Context: New Input Types; detection is per file, so one command can mix them.
def test_detection_is_per_file(ws):
    a = write(ws / "a.csv", "id,v\n3,c\n")
    b = write_tsv(ws / "b.tsv", ["id", "v"], [["1", "a"]])
    c = write_jsonl(ws / "c.jsonl", [{"id": 2, "v": "b"}])
    res = run_ok("--output", "-", "--key", "id", a, b, c)
    assert body(res.stdout) == ["1,a", "2,b", "3,c"]


# --- Spec: "--input-format {auto,csv,tsv,jsonl,parquet}" ---
# Context: Usage; an explicit format overrides the extension for every input.
def test_explicit_input_format_overrides_extension(ws):
    a = write(ws / "a.dat", "id\tv\n7\ta\n")
    res = run_ok("--output", "-", "--key", "id", "--input-format", "tsv", a)
    assert header(res.stdout) == ["id", "v"]
    assert body(res.stdout) == ["7,a"]


# --- Spec: "--input-format {auto,csv,tsv,jsonl,parquet}" ---
# Context: Usage; explicit jsonl on a file whose extension says otherwise.
def test_explicit_input_format_jsonl(ws):
    a = write(ws / "a.txt", '{"id": 1, "v": "a"}\n')
    res = run_ok("--output", "-", "--key", "id", "--input-format", "jsonl", a)
    assert body(res.stdout) == ["1,a"]


# --- Spec: "--input-format {auto,csv,tsv,jsonl,parquet}" ---
# Context: Usage; an unknown value is rejected by the CLI.
def test_unknown_input_format_value_is_rejected(ws):
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--input-format", "orc", a)
    assert res.returncode == 2


# --- Spec: "`--compression=auto` (default): detect `.gz` → gzip; otherwise none" ---
# Context: New Input Types; a non-.gz file is read as plain text.
def test_compression_auto_treats_plain_file_as_none(ws):
    a = write(ws / "a.csv", "id\n7\n")
    res = run_ok("--output", "-", "--key", "id", "--compression", "auto", a)
    assert body(res.stdout) == ["7"]


# --- Spec: "`--compression=gzip` forces gzip" ---
# Context: New Input Types; works on a gzip file whose name lacks .gz.
def test_forced_gzip_on_extensionless_gzip_file(ws):
    a = write_gz(ws / "a.csv", "id,v\n7,a\n")
    res = run_ok("--output", "-", "--key", "id",
                 "--input-format", "csv", "--compression", "gzip", a)
    assert body(res.stdout) == ["7,a"]


# --- Spec: "`--compression=gzip` forces gzip ... Mismatch is error 5" ---
# Context: New Input Types; forcing gzip on plain data is a mismatch.
def test_forced_gzip_on_plain_file_is_error_5(ws):
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--compression", "gzip", a)
    assert res.returncode == 5


# --- Spec: "`--compression=none` forces no decompression ... Mismatch is error 5" ---
# Context: New Input Types; forcing none on gzip data is a mismatch (see T28).
def test_forced_none_on_gzip_file_is_error_5(ws):
    a = write_gz(ws / "a.csv.gz", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--compression", "none", a)
    assert res.returncode == 5


# --- Spec: "detect `.gz` → gzip ... Mismatch is error 5" ---
# Context: New Input Types; a .gz name over plain bytes is a mismatch.
def test_gz_extension_on_plain_bytes_is_error_5(ws):
    a = write(ws / "a.csv.gz", "id\n1\n")
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 5


# --- Spec: "--compression {auto,none,gzip}" applies to every input ---
# Context: Usage; the example passes a glob of uniformly gzipped files.
def test_forced_gzip_applies_to_all_inputs(ws):
    a = write_gz(ws / "a.csv.gz", "id\n2\n")
    b = write_gz(ws / "b.csv.gz", "id\n1\n")
    res = run_ok("--output", "-", "--key", "id", "--compression", "gzip", a, b)
    assert body(res.stdout) == ["1", "2"]


# --- Spec: "Parquet reading must be streamed row group-wise" ---
# Context: New Input Types; gzipped Parquet still reads (see T42).
def test_gzipped_parquet(ws):
    src = write_parquet(ws / "src.parquet", {"id": [2, 1]})
    a = gzip_existing(src, ws / "m.parquet.gz")
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1", "2"]


# --- Spec: "`.parquet` → parquet" with non-Parquet content ---
# Context: New Input Types; extension wins, so the read fails as bad data (T27).
def test_parquet_extension_over_text_is_an_error(ws):
    a = write(ws / "a.parquet", "id,v\n1,a\n")
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode != 0
    assert res.stderr.strip() != ""


# --- Spec: "detect per file by extension" — uppercase names ---
# Context: New Input Types; extension matching is case-insensitive.
def test_extension_detection_is_case_insensitive(ws):
    a = write(ws / "A.CSV", "id\n7\n")
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["7"]
