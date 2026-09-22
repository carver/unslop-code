"""Checkpoint 2 - Sorting and Stability across mixed sources."""
import json

from conftest import (HAVE_PARQUET, needs_parquet, run_tool, write_csv,
                      write_file, write_jsonl, write_parquet, write_schema,
                      write_tsv, body, col)


# --------------------------------------------------------------------------
# Phrase: "Sorting by --key uses casted key values"
# Context: Sorting and Stability.
# --------------------------------------------------------------------------
def test_sort_uses_casted_values_not_text(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "10", "9", "100"])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["9", "10", "100"]


def test_sort_uses_casted_values_across_formats(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "100"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 9}])
    c = write_tsv(tmp_path / "c.tsv", ["id", "10"])
    res = run_tool("--output", "-", "--key", "id", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["9", "10", "100"]


@needs_parquet
def test_sort_across_csv_jsonl_and_parquet(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,src", "3,csv"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 1, "src": "jsonl"}])
    c = write_parquet(tmp_path / "c.parquet", {"id": [2], "src": ["parquet"]})
    res = run_tool("--output", "-", "--key", "id", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "src") == ["jsonl", "parquet", "csv"]


def test_timestamp_key_sorts_chronologically_across_formats(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["ts", "2024-07-01T12:00:00Z"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"ts": "2024-07-01T09:00:00-05:00"}])
    res = run_tool("--output", "-", "--key", "ts", a, b)
    assert res.returncode == 0, res.stderr
    # 09:00-05:00 is 14:00Z, so it sorts after 12:00Z.
    assert col(res.rows(), "ts") == ["2024-07-01T12:00:00Z",
                                     "2024-07-01T14:00:00Z"]


# --------------------------------------------------------------------------
# Phrase: "Keys must exist in resolved schema (error 3 otherwise)"
# Context: Sorting and Stability.
# --------------------------------------------------------------------------
def test_missing_key_column_is_error_3(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "nope", a)
    assert res.returncode == 3
    assert res.stderr.strip() != ""


def test_key_absent_from_provided_schema_is_error_3(tmp_path):
    # The column exists in the input but the provided schema drops it.
    schema = write_schema(tmp_path / "s.json", [("id", "int")])
    a = write_csv(tmp_path / "a.csv", ["id,other", "1,x"])
    res = run_tool("--output", "-", "--key", "other", "--schema", schema, a)
    assert res.returncode == 3


def test_key_present_in_one_source_only_is_fine(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,k", "1,5"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 2}])
    res = run_tool("--output", "-", "--key", "k", a, b)
    assert res.returncode == 0, res.stderr
    # The row with no k sorts first: nulls compare less than non-nulls.
    assert col(res.rows(), "id") == ["2", "1"]


def test_composite_key_missing_second_column_is_error_3(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"ts": 1, "id": 2}])
    res = run_tool("--output", "-", "--key", "ts,nope", a)
    assert res.returncode == 3


def test_error_3_message_names_the_column(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "missing_col", a)
    assert res.returncode == 3
    assert "missing_col" in res.stderr


# --------------------------------------------------------------------------
# Phrase: "Sort must be stable for equal keys"
# Context: Sorting and Stability; equal keys keep input order, which for
#          multiple files means command-line order of the files.
# --------------------------------------------------------------------------
def test_stability_within_one_file(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"k": 1, "n": i} for i in range(6)])
    res = run_tool("--output", "-", "--key", "k", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == [str(i) for i in range(6)]


def test_stability_across_files_follows_argument_order(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["k,n", "1,first"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"k": 1, "n": "second"}])
    c = write_tsv(tmp_path / "c.tsv", ["k\tn", "1\tthird"])
    res = run_tool("--output", "-", "--key", "k", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["first", "second", "third"]
    swapped = run_tool("--output", "-", "--key", "k", c, b, a)
    assert col(swapped.rows(), "n") == ["third", "second", "first"]


def test_stability_holds_when_spilling_to_disk(tmp_path):
    rows = [{"k": 1, "n": i} for i in range(4000)]
    a = write_jsonl(tmp_path / "a.jsonl", rows)
    res = run_tool("--output", "-", "--key", "k",
                   "--memory-limit-mb", "1", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == [str(i) for i in range(4000)]


# --------------------------------------------------------------------------
# Phrase: "--desc" with mixed sources
# Context: Usage; descending applies to the composite key.
# --------------------------------------------------------------------------
def test_desc_reverses_order_across_formats(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 3}])
    c = write_tsv(tmp_path / "c.tsv", ["id", "2"])
    res = run_tool("--output", "-", "--key", "id", "--desc", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["3", "2", "1"]


def test_desc_keeps_stability_for_equal_keys(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["k,n", "1,first"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"k": 1, "n": "second"}])
    res = run_tool("--output", "-", "--key", "k", "--desc", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["first", "second"]


# --------------------------------------------------------------------------
# Phrase: "--key <col>[,<col>...]" composite keys over heterogeneous inputs
# Context: the documented `--key ts,id` example.
# --------------------------------------------------------------------------
@needs_parquet
def test_composite_key_example(tmp_path):
    a = write_csv(tmp_path / "users.csv", ["ts,id,src", "5,2,csv"])
    b = write_jsonl(tmp_path / "events.jsonl",
                    [{"ts": 5, "id": 1, "src": "jsonl"},
                     {"ts": 4, "id": 9, "src": "jsonl"}])
    c = write_parquet(tmp_path / "metrics.parquet",
                      {"ts": [5], "id": [3], "src": ["parquet"]})
    res = run_tool("--output", "-", "--key", "ts,id", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "src") == ["jsonl", "jsonl", "csv", "parquet"]
    assert col(res.rows(), "id") == ["9", "1", "2", "3"]
