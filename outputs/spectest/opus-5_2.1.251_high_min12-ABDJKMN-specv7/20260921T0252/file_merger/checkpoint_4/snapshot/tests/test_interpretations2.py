"""Checkpoint 2 - behaviour chosen where the spec is under-specified.

Each test names the AMBIGUITIES.md entry that records the choice.
"""
import gzip
import json

from conftest import (HAVE_PARQUET, needs_parquet, run_tool, write_bytes,
                      write_csv, write_file, write_gz, write_jsonl,
                      write_parquet, write_schema, write_tsv, body, col)

if HAVE_PARQUET:
    import pyarrow as pa


# --------------------------------------------------------------------------
# T18 - the exit code table. The spec names 2, 3, 5 and 6 only.
# --------------------------------------------------------------------------
def test_t18_usage_error_is_exit_2(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--key", "id", a)  # missing --output
    assert res.returncode == 2


def test_t18_schema_error_is_exit_3(tmp_path):
    bad = write_file(tmp_path / "s.json",
                     json.dumps({"columns": [{"name": "id",
                                              "type": "nonesuch"}]}))
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id", "--schema", bad, a)
    assert res.returncode == 3


def test_t18_cast_failure_under_fail_is_exit_4(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("id", "int")])
    a = write_csv(tmp_path / "a.csv", ["id", "abc"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", a)
    assert res.returncode == 4


def test_t18_unreadable_input_is_exit_1(tmp_path):
    res = run_tool("--output", "-", "--key", "id", str(tmp_path / "gone.csv"))
    assert res.returncode == 1


def test_t18_error_messages_use_the_err_prefix(tmp_path):
    res = run_tool("--output", "-", "--key", "id", str(tmp_path / "gone.csv"))
    assert res.stderr.startswith("ERR 1 ")
    assert res.stderr.count("\n") == 1


def test_t18_success_is_exit_0(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0
    assert res.stderr == ""


# --------------------------------------------------------------------------
# T19 - an unambiguous extension beats the magic bytes.
# --------------------------------------------------------------------------
@needs_parquet
def test_t19_csv_extension_wins_over_parquet_magic(tmp_path):
    tmp = write_parquet(tmp_path / "t.parquet", {"id": [1]})
    src = write_bytes(tmp_path / "weird.csv", open(tmp, "rb").read())
    res = run_tool("--output", "-", "--key", "id", src)
    # Not read as parquet, so the run cannot succeed.
    assert res.returncode != 0


# --------------------------------------------------------------------------
# T20 - a JSONL line that is not a JSON object.
# --------------------------------------------------------------------------
def test_t20_invalid_json_line_is_error_5(tmp_path):
    src = write_file(tmp_path / "a.jsonl", '{"id": 1}\n{not json}\n')
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


def test_t20_top_level_array_line_is_error_5(tmp_path):
    src = write_file(tmp_path / "a.jsonl", '[1, 2]\n')
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


def test_t20_top_level_scalar_line_is_error_5(tmp_path):
    src = write_file(tmp_path / "a.jsonl", '42\n')
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


def test_t20_json_array_document_is_not_ndjson(tmp_path):
    src = write_file(tmp_path / "a.jsonl", '[{"id": 1}, {"id": 2}]\n')
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


# --------------------------------------------------------------------------
# T21 - an empty TSV (no header row at all).
# --------------------------------------------------------------------------
def test_t21_empty_tsv_is_error_5(tmp_path):
    src = write_file(tmp_path / "a.tsv", "")
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.returncode == 5


def test_t21_tsv_with_header_only_is_fine(tmp_path):
    a = write_tsv(tmp_path / "a.tsv", ["id\tv"])
    b = write_tsv(tmp_path / "b.tsv", ["id\tv", "1\tx"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.returncode == 0, res.stderr
    assert len(body(res.rows())) == 1


# --------------------------------------------------------------------------
# T22 - consensus tie-breaking: every file supports `string`, so the winner
#       is the most specific type that a majority supports.
# --------------------------------------------------------------------------
def test_t22_consensus_prefers_specific_type_over_universal_string(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,7"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,8"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "consensus", a, b)
    assert res.returncode == 0, res.stderr
    # string is supported by both too, but int is more specific.
    assert col(res.rows(), "v") == ["7", "8"]


def test_t22_consensus_uses_type_priority_for_ties(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,1"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,0"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "consensus", a, b)
    assert res.returncode == 0, res.stderr
    # bool outranks int in the checkpoint-1 priority list.
    assert col(res.rows(), "v") == ["true", "false"]


# --------------------------------------------------------------------------
# T23 - union folds per-file types through a widening lattice.
# --------------------------------------------------------------------------
def test_t23_union_bool_and_int_widen_to_string(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,true"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,7"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "union", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["true", "7"]


def test_t23_union_of_one_file_is_that_files_type(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,2.5"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "union", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["2.5"]


# --------------------------------------------------------------------------
# T24 - typed sources map onto the checkpoint-1 type vocabulary; the cast
#       rules are then applied to the canonical text of the value.
# --------------------------------------------------------------------------
@needs_parquet
def test_t24_parquet_bool_cast_to_int_schema_fails(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("b", "int")])
    src = write_parquet(tmp_path / "a.parquet", {"id": [1], "b": [True]})
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "b") == [""]


def test_t24_jsonl_int_one_casts_to_bool(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("b", "bool")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "b": 1}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "b") == ["true"]


@needs_parquet
def test_t24_parquet_date_casts_to_timestamp_schema(tmp_path):
    import datetime
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("d", "timestamp")])
    pschema = pa.schema([("id", pa.int64()), ("d", pa.date32())])
    src = write_parquet(tmp_path / "a.parquet",
                        {"id": [1], "d": [datetime.date(2024, 7, 1)]},
                        schema=pschema)
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "d") == ["2024-07-01T00:00:00Z"]


# --------------------------------------------------------------------------
# T25 - --schema accepts an inline JSON document as well as a path.
# --------------------------------------------------------------------------
def test_t25_schema_may_be_inline_json(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": 2}])
    doc = json.dumps({"columns": [{"name": "id", "type": "int"},
                                  {"name": "v", "type": "string"}]})
    res = run_tool("--output", "-", "--key", "id", "--schema", doc, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["2"]


def test_t25_schema_path_still_works(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("id", "int")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr


# --------------------------------------------------------------------------
# T26 - a parquet file with duplicated column names.
# --------------------------------------------------------------------------
@needs_parquet
def test_t26_duplicate_parquet_columns_first_wins(tmp_path):
    pschema = pa.schema([("id", pa.int64()), ("v", pa.string()),
                         ("v", pa.string())])
    table = pa.table([pa.array([1]), pa.array(["first"]),
                      pa.array(["second"])], schema=pschema)
    import pyarrow.parquet as pq
    path = str(tmp_path / "a.parquet")
    pq.write_table(table, path)
    res = run_tool("--output", "-", "--key", "id", path)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["first"]


# --------------------------------------------------------------------------
# T27 - the null literal is recognised on input for CSV/TSV text cells only.
# --------------------------------------------------------------------------
def test_t27_null_literal_recognised_in_tsv_input(tmp_path):
    # Nulls sort before non-nulls, which is how the reading is observable.
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_tsv(tmp_path / "a.tsv", ["id\tv", "1\tNA", "2\tAAA"])
    res = run_tool("--output", "-", "--key", "v", "--schema", schema,
                   "--csv-null-literal", "NA", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2"]


def test_t27_null_literal_not_applied_to_jsonl_strings(tmp_path):
    # A JSONL string is typed data, not CSV text, so the CSV null literal
    # does not turn it into a null on input: "AAA" sorts before "NA".
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"id": 1, "v": "NA"}, {"id": 2, "v": "AAA"}])
    res = run_tool("--output", "-", "--key", "v", "--schema", schema,
                   "--csv-null-literal", "NA", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["2", "1"]
