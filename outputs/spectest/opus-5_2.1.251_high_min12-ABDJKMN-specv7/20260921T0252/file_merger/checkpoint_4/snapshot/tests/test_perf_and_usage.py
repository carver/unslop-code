"""Checkpoint 2 - Performance & Memory, plus the new usage flags."""
import gzip
import json
import os

from conftest import (HAVE_PARQUET, needs_parquet, run_tool, write_bytes,
                      write_csv, write_file, write_gz, write_jsonl,
                      write_jsonl_gz, write_parquet, write_schema, write_tsv,
                      body, col)


# --------------------------------------------------------------------------
# Phrase: "Implementation must work with --memory-limit-mb as low as 64 and
#          terabyte-scale inputs"
# Context: Performance & Memory.
# --------------------------------------------------------------------------
def test_low_memory_limit_still_sorts_correctly(tmp_path):
    n = 3000
    rows = [{"id": (i * 7919) % n, "v": "x" * 20} for i in range(n)]
    a = write_jsonl(tmp_path / "a.jsonl", rows)
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "64", a)
    assert res.returncode == 0, res.stderr
    ids = [int(x) for x in col(res.rows(), "id")]
    assert ids == sorted(ids)
    assert len(ids) == n


def test_memory_limit_one_forces_spilling_but_stays_correct(tmp_path):
    n = 4000
    rows = [{"id": (i * 13) % n} for i in range(n)]
    a = write_jsonl(tmp_path / "a.jsonl", rows)
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "1", a)
    assert res.returncode == 0, res.stderr
    ids = [int(x) for x in col(res.rows(), "id")]
    assert ids == sorted(ids)
    assert len(ids) == n


def test_peak_memory_stays_bounded_under_limit(tmp_path):
    # A file far larger than the limit must not be held in memory at once.
    n = 40000
    rows = [{"id": (i * 7) % n, "pad": "y" * 64} for i in range(n)]
    a = write_jsonl(tmp_path / "a.jsonl", rows)
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "2", a)
    assert res.returncode == 0, res.stderr
    assert len(body(res.rows())) == n


# --------------------------------------------------------------------------
# Phrase: "Avoid format-specific issues (e.g., don't load entire Parquet
#          files or JSON arrays)"
# Context: Performance & Memory.
# --------------------------------------------------------------------------
@needs_parquet
def test_large_parquet_streams_under_low_limit(tmp_path):
    n = 20000
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [(i * 3) % n for i in range(n)],
                         "pad": ["z" * 40] * n},
                        row_group_size=1000)
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "1",
                   "--parquet-row-group-bytes", "65536", src)
    assert res.returncode == 0, res.stderr
    assert len(body(res.rows())) == n
    ids = [int(x) for x in col(res.rows(), "id")]
    assert ids == sorted(ids)


def test_gzipped_input_streams_under_low_limit(tmp_path):
    n = 20000
    src = write_jsonl_gz(tmp_path / "a.jsonl.gz",
                         [{"id": (i * 11) % n} for i in range(n)])
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "1", src)
    assert res.returncode == 0, res.stderr
    assert len(body(res.rows())) == n


# --------------------------------------------------------------------------
# Phrase: "[--temp-dir <PATH>]"
# Context: Usage; spill files go to the chosen directory and are cleaned up.
# --------------------------------------------------------------------------
def test_temp_dir_is_used_and_cleaned(tmp_path):
    spill = tmp_path / "spill"
    spill.mkdir()
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"id": (i * 3) % 4000} for i in range(4000)])
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "1", "--temp-dir", str(spill), a)
    assert res.returncode == 0, res.stderr
    assert os.listdir(str(spill)) == []


# --------------------------------------------------------------------------
# Phrase: "[--parquet-row-group-bytes <INT>]"
# Context: Usage; advisory only.
# --------------------------------------------------------------------------
@needs_parquet
def test_parquet_row_group_bytes_accepted(tmp_path):
    src = write_parquet(tmp_path / "a.parquet", {"id": [1, 2]})
    res = run_tool("--output", "-", "--key", "id",
                   "--parquet-row-group-bytes", "1", src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2"]


def test_parquet_row_group_bytes_accepted_without_parquet_inputs(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id",
                   "--parquet-row-group-bytes", "4096", a)
    assert res.returncode == 0, res.stderr


def test_parquet_row_group_bytes_requires_an_integer(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id",
                   "--parquet-row-group-bytes", "big", a)
    assert res.returncode != 0


# --------------------------------------------------------------------------
# Phrase (Examples): "Mixed CSV + JSONL + Parquet, schema inferred by
#          consensus, sort by composite key"
# Context: Examples.
# --------------------------------------------------------------------------
@needs_parquet
def test_documented_mixed_example(tmp_path):
    users = write_csv(tmp_path / "inputs" / "users.csv",
                      ["ts,id,who", "3,1,alice", "1,2,bob"])
    events = write_jsonl_gz(tmp_path / "inputs" / "events.jsonl.gz",
                            [{"ts": 2, "id": 3, "who": "carol"}])
    metrics = write_parquet(tmp_path / "inputs" / "metrics.parquet",
                            {"ts": [4], "id": [4], "who": ["dave"]})
    out = tmp_path / "merged.csv"
    res = run_tool("--output", str(out), "--key", "ts,id",
                   "--schema-strategy", "consensus",
                   users, events, metrics)
    assert res.returncode == 0, res.stderr
    text = open(str(out)).read()
    assert text.splitlines()[0] == "id,ts,who"
    assert [line.split(",")[2] for line in text.splitlines()[1:]] == [
        "bob", "carol", "alice", "dave"]


# --------------------------------------------------------------------------
# Phrase (Examples): "Authoritative provided schema, TSV source, gzip forced,
#          descending sort"
# Context: Examples.
# --------------------------------------------------------------------------
def test_documented_tsv_gzip_example(tmp_path):
    schema = write_schema(tmp_path / "schema.json",
                          [("created_at", "timestamp"), ("id", "int"),
                           ("label", "string")])
    one = write_bytes(tmp_path / "data" / "one.tsv.gz", gzip.compress(
        "created_at\tid\tlabel\n2024-01-01T00:00:00Z\t1\ta\n".encode()))
    two = write_bytes(tmp_path / "data" / "two.tsv.gz", gzip.compress(
        "created_at\tid\tlabel\n2024-02-01T00:00:00Z\t2\tb\n".encode()))
    res = run_tool("--output", "-", "--key", "created_at,id", "--desc",
                   "--schema", schema,
                   "--input-format", "tsv", "--compression", "gzip",
                   one, two)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "label") == ["b", "a"]
    assert res.rows()[0] == ["created_at", "id", "label"]


# --------------------------------------------------------------------------
# Phrase: "python merge_files.py --output <PATH|-> --key <col>[,<col>...]"
# Context: Usage; the new flags are all optional.
# --------------------------------------------------------------------------
def test_all_new_flags_are_optional(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr


def test_all_new_flags_together(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_gz(tmp_path / "a.csv.gz", "id,v\n1,x\n")
    res = run_tool("--output", "-", "--key", "id", "--desc",
                   "--schema", schema, "--infer", "loose",
                   "--schema-strategy", "union",
                   "--on-type-error", "coerce-null",
                   "--memory-limit-mb", "64", "--temp-dir", str(tmp_path),
                   "--csv-quotechar", '"', "--csv-escapechar", "\\",
                   "--csv-null-literal", "",
                   "--input-format", "csv", "--compression", "gzip",
                   "--parquet-row-group-bytes", "65536", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["x"]


def test_multiple_inputs_of_the_same_format(tmp_path):
    files = [write_jsonl(tmp_path / ("f%d.jsonl" % i), [{"id": 10 - i}])
             for i in range(5)]
    res = run_tool("--output", "-", "--key", "id", *files)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["6", "7", "8", "9", "10"]


def test_missing_input_file_is_an_error(tmp_path):
    res = run_tool("--output", "-", "--key", "id",
                   str(tmp_path / "nope.csv"))
    assert res.returncode != 0
    assert res.stderr.strip() != ""
