"""Checkpoint 2 - gzip handling and compression/format mismatches."""
import gzip

from conftest import (needs_parquet, run_tool, write_bytes, write_csv,
                      write_file, write_gz, write_jsonl_gz, write_parquet,
                      col)


# --------------------------------------------------------------------------
# Phrase: "--compression=auto (default): detect .gz -> gzip; otherwise none"
# Context: New Input Types.
# --------------------------------------------------------------------------
def test_auto_detects_gz_suffix(tmp_path):
    src = write_gz(tmp_path / "a.csv.gz", "id,name\n1,a\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_auto_treats_plain_file_as_uncompressed(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "1,a"])
    res = run_tool("--output", "-", "--key", "id",
                   "--compression", "auto", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_compression_auto_is_the_default(tmp_path):
    src = write_gz(tmp_path / "a.csv.gz", "id,name\n1,a\n")
    explicit = run_tool("--output", "-", "--key", "id",
                        "--compression", "auto", src)
    implicit = run_tool("--output", "-", "--key", "id", src)
    assert explicit.returncode == 0, explicit.stderr
    assert explicit.stdout == implicit.stdout


def test_gz_and_plain_inputs_mix_in_one_run(tmp_path):
    a = write_gz(tmp_path / "a.csv.gz", "id,name\n2,b\n")
    b = write_csv(tmp_path / "b.csv", ["id,name", "1,a"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


# --------------------------------------------------------------------------
# Phrase: "--compression=gzip forces gzip"
# Context: matches the documented `--input-format tsv --compression gzip`
#          example invocation.
# --------------------------------------------------------------------------
def test_forced_gzip_on_file_without_gz_suffix(tmp_path):
    src = write_bytes(tmp_path / "a.csv",
                      gzip.compress(b"id,name\n1,a\n"))
    res = run_tool("--output", "-", "--key", "id",
                   "--compression", "gzip", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_forced_gzip_with_forced_tsv(tmp_path):
    src = write_bytes(tmp_path / "data.tsv.gz",
                      gzip.compress("id\tname\n1\ta\n".encode("utf-8")))
    res = run_tool("--output", "-", "--key", "id",
                   "--input-format", "tsv", "--compression", "gzip", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


# --------------------------------------------------------------------------
# Phrase: "--compression=none forces no decompression"
# Context: New Input Types.
# --------------------------------------------------------------------------
def test_forced_none_on_plain_file(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "1,a"])
    res = run_tool("--output", "-", "--key", "id",
                   "--compression", "none", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_forced_none_on_gz_named_plain_file(tmp_path):
    # Not actually compressed, and we said so: the .gz name must not win.
    src = write_file(tmp_path / "a.csv.gz", "id,name\n1,a\n")
    res = run_tool("--output", "-", "--key", "id",
                   "--compression", "none", "--input-format", "csv", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


# --------------------------------------------------------------------------
# Phrase: "Mismatch is error 5"
# Context: directly follows the three --compression modes.
# --------------------------------------------------------------------------
def test_forced_gzip_on_uncompressed_file_is_error_5(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "1,a"])
    res = run_tool("--output", "-", "--key", "id",
                   "--compression", "gzip", src)
    assert res.returncode == 5
    assert res.stderr.strip() != ""


def test_forced_none_on_gzip_bytes_is_error_5(tmp_path):
    src = write_bytes(tmp_path / "a.csv", gzip.compress(b"id,name\n1,a\n"))
    res = run_tool("--output", "-", "--key", "id",
                   "--compression", "none", src)
    assert res.returncode == 5


def test_gz_suffix_but_not_gzip_bytes_is_error_5(tmp_path):
    src = write_file(tmp_path / "a.csv.gz", "id,name\n1,a\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


def test_mismatch_error_names_the_file(tmp_path):
    src = write_csv(tmp_path / "plain.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id",
                   "--compression", "gzip", src)
    assert res.returncode == 5
    assert "plain.csv" in res.stderr


def test_truncated_gzip_stream_is_error_5(tmp_path):
    blob = gzip.compress(b"id,name\n" + b"1,a\n" * 200)
    src = write_bytes(tmp_path / "a.csv.gz", blob[:len(blob) // 2])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


# --------------------------------------------------------------------------
# Phrase: "For gzip, allow .gz suffix after base extension" combined with
#          gzipped Parquet.
# Context: detection strips .gz, then applies the base extension rule.
# --------------------------------------------------------------------------
@needs_parquet
def test_parquet_gz_detected_by_extension(tmp_path):
    tmp = write_parquet(tmp_path / "t.parquet", {"id": [1], "name": ["a"]})
    src = write_bytes(tmp_path / "m.parquet.gz",
                      gzip.compress(open(tmp, "rb").read()))
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


@needs_parquet
def test_gzipped_parquet_with_ambiguous_extension_uses_inner_magic(tmp_path):
    tmp = write_parquet(tmp_path / "t.parquet", {"id": [1], "name": ["a"]})
    src = write_bytes(tmp_path / "m.dat.gz",
                      gzip.compress(open(tmp, "rb").read()))
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_gzipped_ambiguous_non_parquet_is_error_2(tmp_path):
    src = write_gz(tmp_path / "m.dat.gz", "id,name\n1,a\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 2
