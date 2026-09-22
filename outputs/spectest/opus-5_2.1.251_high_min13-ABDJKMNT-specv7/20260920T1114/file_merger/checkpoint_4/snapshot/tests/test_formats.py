"""Spec section: New Input Types — per-file format and compression detection."""

import gzip

from conftest import header_of, rows_of


# Phrase: "--input-format=auto (default): detect per file by extension ... .csv -> csv"
# Context: New Input Types.
def test_csv_extension_is_detected(csv_file, run_tool):
    csv_file("a.csv", "id,note\n7,a\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["7", "a"]]


# Phrase: ".tsv -> tsv"
# Context: New Input Types, extension detection.
def test_tsv_extension_is_detected(tsv_file, run_tool):
    tsv_file("a.tsv", "id\tnote\n7\ta\n")
    result = run_tool("--output", "-", "--key", "id", "a.tsv")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["7", "a"]]


# Phrase: ".jsonl/.ndjson -> jsonl"
# Context: New Input Types, extension detection. Both spellings mean JSON Lines.
def test_jsonl_and_ndjson_extensions_are_detected(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1}])
    jsonl_file("b.ndjson", [{"id": 2}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl", "b.ndjson")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1"], ["2"]]


# Phrase: ".parquet -> parquet"
# Context: New Input Types, extension detection.
def test_parquet_extension_is_detected(parquet_file, run_tool):
    parquet_file("a.parquet", {"id": [2, 1]})
    result = run_tool("--output", "-", "--key", "id", "a.parquet")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1"], ["2"]]


# Phrase: "For gzip, allow .gz suffix after base extension (e.g., data.csv.gz)"
# Context: New Input Types. The base extension still selects the format.
def test_gzipped_csv_keeps_its_base_extension(csv_file, gzipped, run_tool):
    gzipped(csv_file("a.csv", "id,note\n7,a\n"))
    result = run_tool("--output", "-", "--key", "id", "a.csv.gz")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["7", "a"]]


# Phrase: "(e.g., ... events.jsonl.gz)"
# Context: New Input Types. Gzip applies to every text format.
def test_gzipped_jsonl_is_read(jsonl_file, gzipped, run_tool):
    gzipped(jsonl_file("events.jsonl", [{"id": 3}, {"id": 1}]))
    result = run_tool("--output", "-", "--key", "id", "events.jsonl.gz")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1"], ["3"]]


# Phrase: "If extension is ambiguous and magic bytes indicate Parquet, treat as parquet"
# Context: New Input Types. Ambiguity T38: no known extension means magic bytes decide.
def test_unknown_extension_with_parquet_magic_is_parquet(parquet_file, run_tool, workdir):
    made = parquet_file("a.parquet", {"id": [5]})
    made.rename(workdir / "mystery.dat")
    result = run_tool("--output", "-", "--key", "id", "mystery.dat")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["5"]]


# Phrase: "otherwise error 2"
# Context: New Input Types. An undetectable extension is a hard error.
def test_unknown_extension_without_parquet_magic_is_error_2(csv_file, run_tool):
    csv_file("mystery.dat", "id,note\n1,a\n")
    result = run_tool("--output", "-", "--key", "id", "mystery.dat")
    assert result.returncode == 2
    assert result.stderr


# Phrase: "--input-format {auto,csv,tsv,jsonl,parquet}"
# Context: Usage. A forced format overrides the extension.
def test_forced_input_format_overrides_the_extension(csv_file, run_tool):
    csv_file("a.dat", "id\tnote\n7\ta\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--input-format", "tsv", "a.dat"
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["7", "a"]]


# Phrase: "--input-format {auto,csv,tsv,jsonl,parquet}"
# Context: Usage. Only the listed values are accepted.
def test_unknown_input_format_is_rejected(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "id", "--input-format", "xml", "a.csv")
    assert result.returncode != 0


# Phrase: "--compression=auto (default): detect .gz -> gzip; otherwise none"
# Context: New Input Types.
def test_compression_auto_reads_plain_and_gzipped_together(
    csv_file, gzipped, run_tool
):
    csv_file("plain.csv", "id\n1\n")
    gzipped(csv_file("zipped.csv", "id\n2\n"))
    result = run_tool("--output", "-", "--key", "id", "plain.csv", "zipped.csv.gz")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1"], ["2"]]


# Phrase: "--compression=gzip forces gzip"
# Context: New Input Types. The name need not end in .gz.
def test_forced_gzip_reads_a_compressed_file_named_plainly(run_tool, workdir):
    with gzip.open(workdir / "a.csv", "wb") as handle:
        handle.write(b"id\n7\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--compression", "gzip", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["7"]]


# Phrase: "--compression=none forces no decompression"
# Context: New Input Types. A plain file named .gz is read verbatim.
def test_forced_none_reads_an_uncompressed_file_named_gz(csv_file, run_tool):
    csv_file("a.csv.gz", "id\n7\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--compression", "none", "a.csv.gz"
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["7"]]


# Phrase: "Mismatch is error 5"
# Context: New Input Types. Forced gzip over uncompressed bytes.
def test_forced_gzip_on_plain_bytes_is_error_5(csv_file, run_tool):
    csv_file("a.csv", "id\n7\n")
    result = run_tool(
        "--output", "-", "--key", "id", "--compression", "gzip", "a.csv"
    )
    assert result.returncode == 5
    assert result.stderr


# Phrase: "Mismatch is error 5"
# Context: New Input Types. Ambiguity T29: forced none over gzip bytes also mismatches.
def test_forced_none_on_gzip_bytes_is_error_5(csv_file, gzipped, run_tool):
    gzipped(csv_file("a.csv", "id\n7\n"))
    result = run_tool(
        "--output", "-", "--key", "id", "--compression", "none", "a.csv.gz"
    )
    assert result.returncode == 5
    assert result.stderr


# Phrase: "--compression {auto,none,gzip}"
# Context: Usage. Only the listed values are accepted.
def test_unknown_compression_is_rejected(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "id", "--compression", "zstd", "a.csv")
    assert result.returncode != 0


# Phrase: "Accepted file types: CSV, TSV, JSON Lines (NDJSON), Parquet"
# Context: New Input Types. One run may mix every accepted type.
def test_all_four_formats_merge_in_one_run(
    csv_file, tsv_file, jsonl_file, parquet_file, run_tool
):
    csv_file("a.csv", "id,src\n1,csv\n")
    tsv_file("b.tsv", "id\tsrc\n2\ttsv\n")
    jsonl_file("c.jsonl", [{"id": 3, "src": "jsonl"}])
    parquet_file("d.parquet", {"id": [4], "src": ["parquet"]})
    result = run_tool(
        "--output", "-", "--key", "id", "a.csv", "b.tsv", "c.jsonl", "d.parquet"
    )
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "src"]
    assert rows_of(result.stdout) == [
        ["1", "csv"], ["2", "tsv"], ["3", "jsonl"], ["4", "parquet"]
    ]


# Phrase: "--parquet-row-group-bytes <INT> ... is advisory for batch sizing"
# Context: New Input Types. The flag changes batching, never the result.
def test_parquet_row_group_bytes_does_not_change_the_output(parquet_file, run_tool):
    parquet_file("a.parquet", {"id": list(range(50, 0, -1))})
    small = run_tool(
        "--output", "-", "--key", "id", "--parquet-row-group-bytes", "1024", "a.parquet"
    )
    large = run_tool(
        "--output", "-", "--key", "id",
        "--parquet-row-group-bytes", "67108864", "a.parquet",
    )
    assert small.returncode == 0, small.stderr
    assert small.stdout == large.stdout
