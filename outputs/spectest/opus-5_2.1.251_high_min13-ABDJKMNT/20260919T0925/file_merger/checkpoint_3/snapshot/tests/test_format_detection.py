"""`--input-format` / `--compression`: per-file detection and forced overrides."""

import gzip


def test_csv_extension_detected(run_cli, csv_file):
    # Spec: "`--input-format=auto` (default): detect per file by extension ... `.csv` → csv"
    a = csv_file("a.csv", "id,note\n7,x\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_tsv_extension_detected(run_cli, text_file):
    # Spec: "`.tsv` → tsv"
    a = text_file("a.tsv", "id\tnote\n7\tx\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_jsonl_extension_detected(run_cli, jsonl_file):
    # Spec: "`.jsonl`/`.ndjson` → jsonl"
    a = jsonl_file("a.jsonl", [{"id": 7, "note": "x"}])
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_ndjson_extension_detected(run_cli, jsonl_file):
    # Spec: "`.jsonl`/`.ndjson` → jsonl"
    a = jsonl_file("a.ndjson", [{"id": 7, "note": "x"}])
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_parquet_extension_detected(run_cli, parquet_file):
    # Spec: "`.parquet` → parquet"
    a = parquet_file("a.parquet", {"id": [7], "note": ["x"]})
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_gz_suffix_after_base_extension_csv(run_cli, csv_file):
    # Spec: "For gzip, allow `.gz` suffix after base extension (e.g., `data.csv.gz` ...)"
    a = csv_file("data.csv.gz", "id,note\n7,x\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_gz_suffix_after_base_extension_jsonl(run_cli, jsonl_file):
    # Spec: "(e.g., `data.csv.gz`, `events.jsonl.gz`)"
    a = jsonl_file("events.jsonl.gz", [{"id": 7, "note": "x"}])
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_gz_suffix_after_base_extension_parquet(run_cli, parquet_file):
    # Spec: "For gzip, allow `.gz` suffix after base extension"
    a = parquet_file("m.parquet.gz", {"id": [7], "note": ["x"]})
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_ambiguous_extension_with_parquet_magic_is_parquet(run_cli, parquet_file):
    # Spec: "If extension is ambiguous and magic bytes indicate Parquet, treat as parquet"
    a = parquet_file("blob.dat", {"id": [7], "note": ["x"]})
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_ambiguous_gzipped_extension_with_parquet_magic_is_parquet(run_cli, parquet_file):
    # Spec: magic-byte detection plus "allow `.gz` suffix after base extension" (AMBIGUITIES T24)
    a = parquet_file("blob.dat.gz", {"id": [7], "note": ["x"]})
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_ambiguous_extension_without_parquet_magic_is_error_2(run_cli, text_file):
    # Spec: "If extension is ambiguous and magic bytes indicate Parquet ...; otherwise error 2"
    a = text_file("mystery.dat", "id,note\n1,x\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 2
    assert "mystery.dat" in result.stderr


def test_no_extension_without_parquet_magic_is_error_2(run_cli, text_file):
    # Spec: "otherwise error 2" (AMBIGUITIES T24: no extension counts as ambiguous)
    a = text_file("mystery", "id,note\n1,x\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 2


def test_input_format_override_reads_unknown_extension(run_cli, text_file):
    # Spec usage: "[--input-format {auto,csv,tsv,jsonl,parquet}]" — an explicit format skips detection
    a = text_file("mystery.dat", "id,note\n7,x\n")
    result = run_cli("--output", "-", "--key", "id", "--input-format", "csv", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_input_format_override_wins_over_extension(run_cli, text_file):
    # Spec: an explicit `--input-format` replaces `auto` detection for every input
    a = text_file("a.csv", "id\tnote\n7\tx\n")
    result = run_cli("--output", "-", "--key", "id", "--input-format", "tsv", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["7", "x"]]


def test_compression_auto_detects_gz_suffix(run_cli, csv_file):
    # Spec: "`--compression=auto` (default): detect `.gz` → gzip; otherwise none"
    plain = csv_file("plain.csv", "id\n7\n")
    zipped = csv_file("zipped.csv.gz", "id\n8\n")
    result = run_cli("--output", "-", "--key", "id", plain, zipped)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id"], ["7"], ["8"]]


def test_compression_gzip_forced_on_unsuffixed_file(run_cli, tmp_path):
    # Spec: "`--compression=gzip` forces gzip"
    a = tmp_path / "a.csv"
    a.write_bytes(gzip.compress(b"id\n7\n"))
    result = run_cli("--output", "-", "--key", "id", "--compression", "gzip", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id"], ["7"]]


def test_compression_none_forced_on_plain_file_named_gz(run_cli, tmp_path):
    # Spec: "`--compression=none` forces no decompression"
    a = tmp_path / "a.csv.gz"
    a.write_bytes(b"id\n7\n")
    result = run_cli("--output", "-", "--key", "id", "--compression", "none", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id"], ["7"]]


def test_forced_gzip_on_plain_file_is_error_5(run_cli, csv_file):
    # Spec: "`--compression=gzip` forces gzip ... Mismatch is error 5"
    a = csv_file("a.csv", "id\n1\n")
    result = run_cli("--output", "-", "--key", "id", "--compression", "gzip", a)
    assert result.returncode == 5
    assert "a.csv" in result.stderr


def test_forced_none_on_gzip_file_is_error_5(run_cli, csv_file):
    # Spec: "Mismatch is error 5" (AMBIGUITIES T23: checked in both directions)
    a = csv_file("a.csv.gz", "id\n1\n")
    result = run_cli("--output", "-", "--key", "id", "--compression", "none", a)
    assert result.returncode == 5


def test_auto_compression_gz_name_without_gzip_bytes_is_error_5(run_cli, tmp_path):
    # Spec: "detect `.gz` → gzip ... Mismatch is error 5"
    a = tmp_path / "a.csv.gz"
    a.write_bytes(b"id\n1\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 5


def test_parquet_row_group_bytes_is_advisory(run_cli, parquet_file):
    # Spec: "`--parquet-row-group-bytes` is advisory for batch sizing"
    a = parquet_file("a.parquet", {"id": [3, 1, 2]})
    result = run_cli("--output", "-", "--key", "id", "--parquet-row-group-bytes", "4096", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id"], ["1"], ["2"], ["3"]]


def test_unreadable_input_reports_the_path(run_cli, tmp_path):
    # Spec: inputs are read from the command line; a missing one is a fatal error
    result = run_cli("--output", "-", "--key", "id", tmp_path / "nope.csv")
    assert result.returncode != 0
    assert "nope.csv" in result.stderr
