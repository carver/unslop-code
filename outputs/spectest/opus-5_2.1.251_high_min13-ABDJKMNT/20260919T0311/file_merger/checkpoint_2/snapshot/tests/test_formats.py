"""Spec section: New Input Types — format and compression detection."""
import gzip

import pyarrow as pa
import pyarrow.parquet as pq
from conftest import column


# Phrase: "--input-format=auto (default): detect per file by extension ... .csv -> csv"
# Context: the extension alone decides, with no sniffing of a recognised suffix.
def test_csv_extension_detected(run, csv_file):
    csv_file("a.csv", "id,v\n1,x\n")
    assert column(run("--output", "-", "--key", "id", "a.csv").stdout, "v") == ["x"]


# Phrase: "detect per file by extension ... .tsv -> tsv"
def test_tsv_extension_detected(run, text_file):
    text_file("a.tsv", "id\tv\n1\tx\n")
    assert column(run("--output", "-", "--key", "id", "a.tsv").stdout, "v") == ["x"]


# Phrase: "detect per file by extension ... .jsonl/.ndjson -> jsonl"
def test_jsonl_and_ndjson_extensions_detected(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "v": "x"}])
    jsonl_file("b.ndjson", [{"id": 2, "v": "y"}])
    res = run("--output", "-", "--key", "id", "a.jsonl", "b.ndjson")
    assert column(res.stdout, "v") == ["x", "y"]


# Phrase: "detect per file by extension ... .parquet -> parquet"
def test_parquet_extension_detected(run, parquet_file):
    parquet_file("a.parquet", {"id": ([1], pa.int64()), "v": (["x"], pa.string())})
    assert column(run("--output", "-", "--key", "id", "a.parquet").stdout, "v") == ["x"]


# Phrase: "For gzip, allow .gz suffix after base extension (e.g., data.csv.gz, events.jsonl.gz)"
# Context: the base extension still selects the format; .gz only selects decompression.
def test_gz_suffix_after_base_extension(run, gz_file):
    gz_file("data.csv.gz", "id,v\n1,x\n")
    gz_file("events.jsonl.gz", '{"id": 2, "v": "y"}\n')
    res = run("--output", "-", "--key", "id", "data.csv.gz", "events.jsonl.gz")
    assert column(res.stdout, "v") == ["x", "y"]


# Phrase: "If extension is ambiguous and magic bytes indicate Parquet, treat as parquet"
def test_ambiguous_extension_with_parquet_magic(run, tmp_path, parquet_file):
    parquet_file("real.parquet", {"id": ([7], pa.int64())})
    (tmp_path / "mystery.dat").write_bytes((tmp_path / "real.parquet").read_bytes())
    res = run("--output", "-", "--key", "id", "mystery.dat")
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "id") == ["7"]


# Phrase: "If extension is ambiguous ... otherwise error 2"
# Context: T20/T26 — an unrecognised extension over non-Parquet bytes exits 2.
def test_ambiguous_extension_without_parquet_magic_is_error_2(run, text_file):
    text_file("mystery.dat", "id,v\n1,x\n")
    res = run("--output", "-", "--key", "id", "mystery.dat")
    assert res.returncode == 2
    assert res.stderr.strip().startswith("error:")


# Phrase: "If extension is ambiguous ... otherwise error 2"
# Context: T26 — a file with no extension at all is ambiguous too.
def test_no_extension_without_parquet_magic_is_error_2(run, text_file):
    text_file("noext", "id,v\n1,x\n")
    assert run("--output", "-", "--key", "id", "noext").returncode == 2


# Phrase: "[--input-format {auto,csv,tsv,jsonl,parquet}]"
# Context: an explicit format overrides whatever the extension says.
def test_explicit_input_format_overrides_extension(run, text_file):
    text_file("a.dat", "id\tv\n1\tx\n")
    res = run("--output", "-", "--key", "id", "--input-format", "tsv", "a.dat")
    assert column(res.stdout, "v") == ["x"]


# Phrase: "--compression=auto (default): detect .gz -> gzip; otherwise none"
def test_compression_auto_detects_gz(run, gz_file, csv_file):
    gz_file("z.csv.gz", "id\n1\n")
    csv_file("p.csv", "id\n2\n")
    res = run("--output", "-", "--key", "id", "z.csv.gz", "p.csv")
    assert column(res.stdout, "id") == ["1", "2"]


# Phrase: "--compression=gzip forces gzip"
# Context: a gzip file whose name does not end in .gz still reads.
def test_compression_gzip_forced(run, tmp_path):
    with gzip.open(tmp_path / "a.csv", "wb") as fh:
        fh.write(b"id\n5\n")
    res = run("--output", "-", "--key", "id", "--compression", "gzip", "a.csv")
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "id") == ["5"]


# Phrase: "--compression=none forces no decompression" / "Mismatch is error 5"
# Context: T25 — forcing none over gzip bytes is a mismatch.
def test_forced_none_over_gzip_bytes_is_error_5(run, gz_file):
    gz_file("a.csv.gz", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--compression", "none", "a.csv.gz")
    assert res.returncode == 5


# Phrase: "Mismatch is error 5"
# Context: T25 — forcing gzip over plain bytes is the other direction.
def test_forced_gzip_over_plain_bytes_is_error_5(run, csv_file):
    csv_file("a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--compression", "gzip", "a.csv")
    assert res.returncode == 5
    assert res.stderr.strip().startswith("error:")


# Phrase: "--compression=auto ... detect .gz -> gzip"
# Context: a .gz name over plain bytes is the same mismatch.
def test_gz_named_plain_file_is_error_5(run, csv_file):
    csv_file("a.csv.gz", "id\n1\n")
    assert run("--output", "-", "--key", "id", "a.csv.gz").returncode == 5


# Phrase: "Parquet reading must be streamed row group-wise"
# Context: [--parquet-row-group-bytes <INT>] is advisory and never changes output.
def test_parquet_row_group_bytes_is_advisory(run, tmp_path):
    ids = list(range(500))
    table_ = pa.table({"id": pa.array(ids, pa.int64())})
    pq.write_table(table_, tmp_path / "a.parquet", row_group_size=50)
    small = run("--output", "-", "--key", "id", "--parquet-row-group-bytes", "512", "a.parquet")
    big = run("--output", "-", "--key", "id", "--parquet-row-group-bytes", "9999999", "a.parquet")
    assert small.returncode == 0, small.stderr
    assert small.stdout == big.stdout
    assert column(small.stdout, "id") == [str(i) for i in ids]


# Phrase: "Accepted file types: CSV, TSV, JSON Lines (NDJSON), Parquet"
# Context: all four formats can appear in one invocation.
def test_all_four_formats_in_one_run(run, csv_file, text_file, jsonl_file, parquet_file):
    csv_file("a.csv", "id,src\n1,csv\n")
    text_file("b.tsv", "id\tsrc\n2\ttsv\n")
    jsonl_file("c.jsonl", [{"id": 3, "src": "jsonl"}])
    parquet_file("d.parquet", {"id": ([4], pa.int64()), "src": (["parquet"], pa.string())})
    res = run("--output", "-", "--key", "id", "a.csv", "b.tsv", "c.jsonl", "d.parquet")
    assert res.returncode == 0, res.stderr
    assert column(res.stdout, "src") == ["csv", "tsv", "jsonl", "parquet"]
