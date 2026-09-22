"""Spec section: Determinism Checklist - "Exact exit codes and stderr message shape"."""
from conftest import body


def assert_error_shape(result):
    assert result.stdout == ""
    assert result.stderr.startswith("merge_files.py: error: ")
    assert result.stderr.endswith("\n")


# Phrase: "If extension is ambiguous and magic bytes indicate Parquet, treat as
#          parquet; otherwise error 2"
# Context: New Input Types.
def test_undetectable_format_exits_2(run, work):
    work.write("a.bin", "id\n1\n")
    r = run("--output", "-", "--key", "id", work.path("a.bin"))
    assert r.returncode == 2
    assert_error_shape(r)


# Phrase: "Keys must exist in resolved schema (error 3 otherwise)"
# Context: Sorting and Stability.
def test_unknown_key_exits_3(run, work):
    work.jsonl("a.jsonl", [{"id": 1}])
    r = run("--output", "-", "--key", "missing", work.path("a.jsonl"))
    assert r.returncode == 3
    assert_error_shape(r)


# Phrase: "On cast failure, follow `--on-type-error` from checkpoint 1"
# Context: Casting; `fail` writes to stderr and exits non-zero.
def test_cast_failure_exits_nonzero_with_message(run, work):
    work.schema("s.json", [("id", "int"), ("n", "int")])
    work.csv("a.csv", ["id", "n"], [["5", "abc"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.csv"),
    )
    assert r.returncode == 4
    assert_error_shape(r)


# Phrase: "Mismatch is error 5"
# Context: New Input Types.
def test_compression_mismatch_exits_5(run, work):
    work.csv("a.csv", ["id"], [["5"]])
    r = run(
        "--output", "-", "--key", "id", "--compression", "gzip", work.path("a.csv")
    )
    assert r.returncode == 5
    assert_error_shape(r)


# Phrase: "nested fields trigger error 6"
# Context: Source Dialect Assumptions.
def test_nested_exits_6(run, work):
    work.jsonl("a.jsonl", [{"id": 1, "o": {"k": 1}}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 6
    assert_error_shape(r)


# Phrase: "<INPUT1> [<INPUT2> ...]"
# Context: Usage; an unreadable input is a plain I/O failure.
def test_missing_input_exits_1(run, work):
    r = run("--output", "-", "--key", "id", work.path("nope.csv"))
    assert r.returncode == 1
    assert_error_shape(r)


# Phrase: "--input-format {auto,csv,tsv,jsonl,parquet}"
# Context: Usage; argparse rejects an unknown choice before any work happens.
def test_bad_flag_choice_exits_2(run, work):
    work.csv("a.csv", ["id"], [["5"]])
    r = run(
        "--output", "-", "--key", "id", "--compression", "bz2", work.path("a.csv")
    )
    assert r.returncode == 2


# Phrase: "detect per file by extension and magic bytes"
# Context: New Input Types; a gzipped Parquet file with an unhelpful name.
def test_gzipped_parquet_detected_by_magic(run, work):
    src = work.parquet("real.parquet", [{"id": 4}, {"id": 2}])
    work.gzip_file("mystery.bin.gz", src)
    r = run("--output", "-", "--key", "id", work.path("mystery.bin.gz"))
    assert r.ok, r.stderr
    assert body(r) == [["2"], ["4"]]
