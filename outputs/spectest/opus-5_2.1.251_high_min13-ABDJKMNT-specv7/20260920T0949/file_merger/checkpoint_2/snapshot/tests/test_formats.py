"""Per-file format and compression detection."""

from conftest import rows_of


# Spec: "--input-format=auto (default): detect per file by extension and magic bytes:
# `.csv` -> csv, `.tsv` -> tsv, `.jsonl`/`.ndjson` -> jsonl, `.parquet` -> parquet"
def test_extension_selects_the_reader_for_each_input(make_csv, make_text, make_jsonl, make_parquet, run):
    make_csv("a.csv", "id,v\n1,c\n")
    make_text("b.tsv", "id\tv\n2\tt\n")
    make_jsonl("c.jsonl", [{"id": 3, "v": "j"}])
    make_parquet("d.parquet", {"id": [4], "v": ["p"]})
    proc = run("--output", "-", "--key", "id", "a.csv", "b.tsv", "c.jsonl", "d.parquet")
    assert rows_of(proc.stdout) == [["id", "v"], ["1", "c"], ["2", "t"], ["3", "j"], ["4", "p"]]


# Spec: "`.jsonl`/`.ndjson` -> jsonl"
def test_ndjson_extension_is_read_as_jsonl(make_jsonl, run):
    make_jsonl("a.ndjson", [{"id": 7}])
    proc = run("--output", "-", "--key", "id", "a.ndjson")
    assert rows_of(proc.stdout) == [["id"], ["7"]]


# Spec: "For gzip, allow `.gz` suffix after base extension (e.g., `data.csv.gz`, `events.jsonl.gz`)"
def test_gz_suffix_after_base_extension_keeps_the_base_format(make_csv, make_jsonl, gzipped, run):
    gzipped(make_csv("a.csv", "id,v\n1,c\n"))
    gzipped(make_jsonl("b.jsonl", [{"id": 2, "v": "j"}]))
    proc = run("--output", "-", "--key", "id", "a.csv.gz", "b.jsonl.gz")
    assert rows_of(proc.stdout) == [["id", "v"], ["1", "c"], ["2", "j"]]


# Spec: "--compression=auto (default): detect `.gz` -> gzip; otherwise none"
def test_plain_file_is_not_decompressed_under_auto(make_csv, run):
    make_csv("a.csv", "id\n7\n")
    proc = run("--output", "-", "--key", "id", "--compression", "auto", "a.csv")
    assert rows_of(proc.stdout) == [["id"], ["7"]]


# Spec: "If extension is ambiguous and magic bytes indicate Parquet, treat as parquet"
def test_unknown_extension_with_parquet_magic_is_read_as_parquet(make_parquet, run):
    make_parquet("data.bin", {"id": [1]})
    proc = run("--output", "-", "--key", "id", "data.bin")
    assert rows_of(proc.stdout) == [["id"], ["1"]]


# Spec: "If extension is ambiguous and magic bytes indicate Parquet, treat as parquet; otherwise error 2"
def test_unknown_extension_without_parquet_magic_exits_2(make_text, run):
    make_text("data.dat", "id,v\n1,x\n")
    proc = run("--output", "-", "--key", "id", "data.dat", expect_ok=False)
    assert proc.returncode == 2
    assert proc.stderr.strip()


# Spec: "[--input-format {auto,csv,tsv,jsonl,parquet}]"
# Context: an explicit format overrides what the extension says.
def test_input_format_overrides_the_extension(make_text, run):
    make_text("data.dat", "id\tv\n7\tx\n")
    proc = run("--output", "-", "--key", "id", "--input-format", "tsv", "data.dat")
    assert rows_of(proc.stdout) == [["id", "v"], ["7", "x"]]


# Spec: "--compression=gzip forces gzip" (usage example: --input-format tsv --compression gzip data/*.tsv.gz)
def test_forced_format_and_compression_read_a_gzipped_tsv(make_text, gzipped, run):
    gzipped(make_text("data.tsv", "id\tv\n7\tx\n"))
    proc = run(
        "--output", "-", "--key", "id",
        "--input-format", "tsv", "--compression", "gzip", "data.tsv.gz",
    )
    assert rows_of(proc.stdout) == [["id", "v"], ["7", "x"]]


# Spec: "--compression=gzip forces gzip ... Mismatch is error 5"
# Context: see AMBIGUITIES T23 - the magic bytes are what a forced flag can contradict.
def test_forced_gzip_on_a_plain_file_exits_5(make_csv, run):
    make_csv("a.csv", "id\n1\n")
    proc = run("--output", "-", "--key", "id", "--compression", "gzip", "a.csv", expect_ok=False)
    assert proc.returncode == 5
    assert proc.stderr.strip()


# Spec: "--compression=none forces no decompression ... Mismatch is error 5"
def test_forced_none_on_a_gzip_file_exits_5(make_csv, gzipped, run):
    gzipped(make_csv("a.csv", "id\n1\n"))
    proc = run("--output", "-", "--key", "id", "--compression", "none", "a.csv.gz", expect_ok=False)
    assert proc.returncode == 5


# Spec: "--compression=auto (default): detect `.gz` -> gzip" together with "Mismatch is error 5"
def test_gz_extension_on_a_plain_file_exits_5(make_text, run):
    make_text("a.csv.gz", "id\n1\n")
    proc = run("--output", "-", "--key", "id", "a.csv.gz", expect_ok=False)
    assert proc.returncode == 5


# Spec: "detect per file by extension and magic bytes"
# Context: see AMBIGUITIES T23 - in auto mode gzip content is recognised even
# without the .gz name.
def test_gzip_content_without_gz_extension_is_decompressed_under_auto(make_csv, gzipped, run):
    gzipped(make_csv("a.csv", "id\n7\n"), name="b.csv")
    proc = run("--output", "-", "--key", "id", "b.csv")
    assert rows_of(proc.stdout) == [["id"], ["7"]]


# Spec: "detect per file by extension" - detection is per file, not per run.
def test_detection_is_per_file(make_csv, make_jsonl, gzipped, run):
    make_csv("a.csv", "id\n1\n")
    gzipped(make_jsonl("b.jsonl", [{"id": 2}]))
    proc = run("--output", "-", "--key", "id", "a.csv", "b.jsonl.gz")
    assert rows_of(proc.stdout) == [["id"], ["1"], ["2"]]


# Spec: "[--parquet-row-group-bytes <INT>]" - "advisory for batch sizing"
# Context: it changes batch sizes only, never the merged output.
def test_parquet_row_group_bytes_does_not_change_the_output(make_parquet, run):
    make_parquet("a.parquet", {"id": [3, 1, 2]})
    small = run("--output", "-", "--key", "id", "--parquet-row-group-bytes", "64", "a.parquet")
    large = run("--output", "-", "--key", "id", "--parquet-row-group-bytes", "8388608", "a.parquet")
    assert small.stdout == large.stdout == "id\n1\n2\n3\n"


# Spec: "[--parquet-row-group-bytes <INT>]"
def test_parquet_row_group_bytes_must_be_an_integer(make_parquet, run):
    make_parquet("a.parquet", {"id": [1]})
    proc = run("--output", "-", "--key", "id", "--parquet-row-group-bytes", "big", "a.parquet", expect_ok=False)
    assert proc.returncode == 2


# Spec: "[--input-format {auto,csv,tsv,jsonl,parquet}]" and "[--compression {auto,none,gzip}]"
def test_format_and_compression_choices_are_restricted(make_csv, run):
    make_csv("a.csv", "id\n1\n")
    assert run("--output", "-", "--key", "id", "--input-format", "orc", "a.csv", expect_ok=False).returncode == 2
    assert run("--output", "-", "--key", "id", "--compression", "zstd", "a.csv", expect_ok=False).returncode == 2
