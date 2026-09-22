"""Checkpoint 2 - New Input Types: detection by extension and magic bytes."""
import gzip
import json

from conftest import (needs_parquet, run_tool, write_bytes, write_csv,
                      write_file, write_gz, write_jsonl, write_jsonl_gz,
                      write_parquet, write_tsv, col, body)


# --------------------------------------------------------------------------
# Phrase: "Accepted file types: CSV, TSV, JSON Lines (NDJSON), Parquet"
# Context: New Input Types.
# --------------------------------------------------------------------------
def test_csv_input_still_accepted(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "2,b", "1,a"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


def test_tsv_input_accepted(tmp_path):
    src = write_tsv(tmp_path / "a.tsv", ["id\tname", "2\tb", "1\ta"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


def test_jsonl_input_accepted(tmp_path):
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 2, "name": "b"}, {"id": 1, "name": "a"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


def test_ndjson_extension_accepted(tmp_path):
    src = write_jsonl(tmp_path / "a.ndjson",
                      [{"id": 2, "name": "b"}, {"id": 1, "name": "a"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


@needs_parquet
def test_parquet_input_accepted(tmp_path):
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [2, 1], "name": ["b", "a"]})
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


# --------------------------------------------------------------------------
# Phrase: "--input-format=auto (default): detect per file by extension and
#          magic bytes: .csv -> csv, .tsv -> tsv, .jsonl/.ndjson -> jsonl,
#          .parquet -> parquet"
# Context: detection happens per file, so one run may mix all four.
# --------------------------------------------------------------------------
@needs_parquet
def test_detection_is_per_file(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,src", "1,csv"])
    b = write_tsv(tmp_path / "b.tsv", ["id\tsrc", "2\ttsv"])
    c = write_jsonl(tmp_path / "c.jsonl", [{"id": 3, "src": "jsonl"}])
    d = write_parquet(tmp_path / "d.parquet", {"id": [4], "src": ["parquet"]})
    res = run_tool("--output", "-", "--key", "id", a, b, c, d)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "src") == ["csv", "tsv", "jsonl", "parquet"]


def test_tsv_extension_is_not_parsed_as_csv(tmp_path):
    # A .tsv file whose fields contain commas must not split on the comma.
    src = write_tsv(tmp_path / "a.tsv", ["id\tname", "1\tx,y"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["x,y"]


def test_csv_extension_is_not_parsed_as_tsv(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "1,x\ty"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["x\ty"]


def test_extension_detection_is_case_insensitive(tmp_path):
    src = write_csv(tmp_path / "A.CSV", ["id,name", "1,a"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


# --------------------------------------------------------------------------
# Phrase: "For gzip, allow .gz suffix after base extension
#          (e.g., data.csv.gz, events.jsonl.gz)"
# Context: the base extension before .gz selects the format.
# --------------------------------------------------------------------------
def test_csv_gz_detected(tmp_path):
    src = write_gz(tmp_path / "data.csv.gz", "id,name\n2,b\n1,a\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


def test_jsonl_gz_detected(tmp_path):
    src = write_jsonl_gz(tmp_path / "events.jsonl.gz",
                         [{"id": 2, "name": "b"}, {"id": 1, "name": "a"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


def test_tsv_gz_detected(tmp_path):
    src = write_gz(tmp_path / "data.tsv.gz", "id\tname\n2\tb\n1\ta\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


def test_ndjson_gz_detected(tmp_path):
    src = write_jsonl_gz(tmp_path / "e.ndjson.gz", [{"id": 1, "name": "a"}])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


# --------------------------------------------------------------------------
# Phrase: "If extension is ambiguous and magic bytes indicate Parquet, treat
#          as parquet; otherwise error 2"
# Context: unknown/absent extension.
# --------------------------------------------------------------------------
@needs_parquet
def test_unknown_extension_with_parquet_magic_is_parquet(tmp_path):
    tmp = write_parquet(tmp_path / "tmp.parquet", {"id": [1], "name": ["a"]})
    raw = open(tmp, "rb").read()
    src = write_bytes(tmp_path / "mystery.dat", raw)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


@needs_parquet
def test_no_extension_with_parquet_magic_is_parquet(tmp_path):
    tmp = write_parquet(tmp_path / "tmp.parquet", {"id": [1], "name": ["a"]})
    raw = open(tmp, "rb").read()
    src = write_bytes(tmp_path / "mystery", raw)
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_unknown_extension_without_parquet_magic_is_error_2(tmp_path):
    src = write_file(tmp_path / "mystery.dat", "id,name\n1,a\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 2
    assert res.stderr.strip() != ""


def test_json_extension_is_ambiguous_error_2(tmp_path):
    # ".json" is not one of the listed extensions; a JSON array is not NDJSON.
    src = write_file(tmp_path / "a.json", json.dumps([{"id": 1}]))
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 2


def test_ambiguous_extension_error_names_the_file(tmp_path):
    src = write_file(tmp_path / "mystery.dat", "id\n1\n")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 2
    assert "mystery.dat" in res.stderr


# --------------------------------------------------------------------------
# Phrase: "--input-format {auto,csv,tsv,jsonl,parquet}"
# Context: an explicit format overrides extension based detection.
# --------------------------------------------------------------------------
def test_forced_format_overrides_extension(tmp_path):
    # Tab separated content stored under a .csv name, read as TSV on demand.
    src = write_file(tmp_path / "a.csv", "id\tname\n1\ta\n")
    res = run_tool("--output", "-", "--key", "id", "--input-format", "tsv", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_forced_format_rescues_ambiguous_extension(tmp_path):
    src = write_file(tmp_path / "mystery.dat", "id,name\n1,a\n")
    res = run_tool("--output", "-", "--key", "id", "--input-format", "csv", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_forced_format_applies_to_every_input(tmp_path):
    a = write_file(tmp_path / "a.dat", "id\tname\n1\ta\n")
    b = write_file(tmp_path / "b.dat", "id\tname\n2\tb\n")
    res = run_tool("--output", "-", "--key", "id", "--input-format", "tsv",
                   a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a", "b"]


def test_forced_jsonl_format(tmp_path):
    src = write_file(tmp_path / "a.log", '{"id": 1, "name": "a"}\n')
    res = run_tool("--output", "-", "--key", "id", "--input-format", "jsonl",
                   src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


@needs_parquet
def test_forced_parquet_format(tmp_path):
    tmp = write_parquet(tmp_path / "t.parquet", {"id": [1], "name": ["a"]})
    src = write_bytes(tmp_path / "a.bin", open(tmp, "rb").read())
    res = run_tool("--output", "-", "--key", "id", "--input-format", "parquet",
                   src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "name") == ["a"]


def test_input_format_rejects_unknown_value(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id", "--input-format", "avro",
                   src)
    assert res.returncode != 0


def test_input_format_auto_is_the_default(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name", "1,a"])
    explicit = run_tool("--output", "-", "--key", "id",
                        "--input-format", "auto", src)
    implicit = run_tool("--output", "-", "--key", "id", src)
    assert explicit.returncode == 0, explicit.stderr
    assert explicit.stdout == implicit.stdout
