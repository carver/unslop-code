"""Checkpoint 2 - Schema Resolution Across Heterogeneous Inputs."""
import json

from conftest import (HAVE_PARQUET, needs_parquet, run_tool, write_csv,
                      write_file, write_jsonl, write_parquet, write_schema,
                      write_tsv, body, col)

if HAVE_PARQUET:
    import pyarrow as pa


# --------------------------------------------------------------------------
# Phrase: "If --schema provided, it defines exact output columns, types, and
#          order"
# Context: Schema Resolution Across Heterogeneous Inputs.
# --------------------------------------------------------------------------
def test_provided_schema_fixes_column_order(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("z", "string"), ("id", "int")])
    a = write_csv(tmp_path / "a.csv", ["id,z", "1,x"])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["z", "id"]


def test_provided_schema_fixes_types_over_jsonl(tmp_path):
    # JSONL carries a number, but the schema says string.
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": 12}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["12"]


@needs_parquet
def test_provided_schema_overrides_parquet_types(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "string")])
    a = write_parquet(tmp_path / "a.parquet", {"id": [1], "n": [7]})
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["7"]


# --------------------------------------------------------------------------
# Phrase: "Extra input columns ignored; missing columns filled with null
#          literal"
# Context: provided --schema.
# --------------------------------------------------------------------------
def test_extra_jsonl_keys_ignored(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("id", "int")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "junk": "drop me"}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["id"]
    assert body(res.rows()) == [["1"]]


@needs_parquet
def test_extra_parquet_columns_ignored(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("id", "int")])
    a = write_parquet(tmp_path / "a.parquet", {"id": [1], "junk": ["x"]})
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert body(res.rows()) == [["1"]]


def test_missing_columns_filled_with_null_literal(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("absent", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "NA", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "absent") == ["NA"]


def test_column_missing_from_one_source_only(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,only_csv", "1,x"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 2, "only_jsonl": "y"}])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["id", "only_csv", "only_jsonl"]
    assert col(res.rows(), "only_csv") == ["x", ""]
    assert col(res.rows(), "only_jsonl") == ["", "y"]


# --------------------------------------------------------------------------
# Phrase: "Column set: union of all encountered field names"
# Context: inferred schema.
# --------------------------------------------------------------------------
@needs_parquet
def test_column_set_is_union_across_formats(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,c", "1,x"])
    b = write_tsv(tmp_path / "b.tsv", ["id\tt", "2\ty"])
    c = write_jsonl(tmp_path / "c.jsonl", [{"id": 3, "j": "z"}])
    d = write_parquet(tmp_path / "d.parquet", {"id": [4], "p": ["w"]})
    res = run_tool("--output", "-", "--key", "id", a, b, c, d)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["c", "id", "j", "p", "t"]


# --------------------------------------------------------------------------
# Phrase: "Column order: ascending lexicographic by column name"
# Context: inferred schema.
# --------------------------------------------------------------------------
def test_inferred_column_order_is_lexicographic(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"zebra": 1, "Apple": 2, "mango": 3, "id": 4}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == sorted(["zebra", "Apple", "mango", "id"])


def test_lexicographic_order_is_codepoint_order(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"B": 1, "a": 2, "id": 3}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["B", "a", "id"]


# --------------------------------------------------------------------------
# Phrase: "Type inference per --infer mode (strict or loose)"
# Context: inferred schema across heterogeneous inputs.
# --------------------------------------------------------------------------
def test_infer_strict_null_forces_string_in_jsonl(tmp_path):
    # strict considers nulls, so a null makes the column fall back to string.
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"id": 1, "n": 5}, {"id": 2, "n": None}])
    res = run_tool("--output", "-", "--key", "id", "--infer", "strict", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["5", ""]


def test_infer_loose_skips_nulls(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"id": 1, "n": 5.5}, {"id": 2, "n": None}])
    res = run_tool("--output", "-", "--key", "id", "--infer", "loose", a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["5.5", ""]


def test_infer_loose_widens_int_and_float_across_files(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,n", "1,3"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 2, "n": 2.5}])
    res = run_tool("--output", "-", "--key", "id", "--infer", "loose", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["3.0", "2.5"]


def test_infer_strict_conflicting_files_fall_back_to_string(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,n", "1,3"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 2, "n": "abc"}])
    res = run_tool("--output", "-", "--key", "id", "--infer", "strict", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["3", "abc"]


# --------------------------------------------------------------------------
# Phrase: "--schema-strategy=authoritative (default): prefer typed sources in
#          precedence order; JSONL ranks equal to CSV."
# Context: Schema disagreement strategy.
# --------------------------------------------------------------------------
@needs_parquet
def test_authoritative_prefers_parquet_type(tmp_path):
    # Parquet declares string; the CSV alone would have inferred int.
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_parquet(tmp_path / "b.parquet", {"id": [2], "v": ["20"]})
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "20"]


@needs_parquet
def test_authoritative_parquet_beats_jsonl(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": 10}])
    b = write_parquet(tmp_path / "b.parquet", {"id": [2], "v": ["x"]})
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "authoritative", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "x"]


@needs_parquet
def test_authoritative_parquet_float_wins_over_csv_ints(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,n", "1,7"])
    b = write_parquet(tmp_path / "b.parquet", {"id": [2], "n": [2.5]})
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "n") == ["7.0", "2.5"]


def test_jsonl_ranks_equal_to_csv_so_conflict_falls_back(tmp_path):
    # If JSONL outranked CSV the column would be int; equal rank means the
    # checkpoint-1 conflict rule applies and the column becomes string.
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": 10}])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,abc"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "abc"]


def test_authoritative_is_the_default_strategy(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,n", "1,3"])
    b = write_csv(tmp_path / "b.csv", ["id,n", "2,x"])
    explicit = run_tool("--output", "-", "--key", "id",
                        "--schema-strategy", "authoritative", a, b)
    implicit = run_tool("--output", "-", "--key", "id", a, b)
    assert explicit.returncode == 0, explicit.stderr
    assert explicit.stdout == implicit.stdout


@needs_parquet
def test_authoritative_ignores_untyped_sources_when_parquet_present(tmp_path):
    # Two CSVs disagree (would be string), but Parquet settles it as int.
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,2.5"])
    c = write_parquet(tmp_path / "c.parquet", {"id": [3], "v": [7]})
    res = run_tool("--output", "-", "--key", "id", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "", "7"]


# --------------------------------------------------------------------------
# Phrase: "--schema-strategy=consensus: choose type that majority of files
#          support"
# Context: Schema disagreement strategy.
# --------------------------------------------------------------------------
def test_consensus_majority_of_files_wins(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,20"])
    c = write_csv(tmp_path / "c.csv", ["id,v", "3,abc"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "consensus", a, b, c)
    assert res.returncode == 0, res.stderr
    # int has 2/3 support; the outlier fails the cast and becomes null.
    assert col(res.rows(), "v") == ["10", "20", ""]


def test_consensus_minority_does_not_win(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,abc"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,def"])
    c = write_csv(tmp_path / "c.csv", ["id,v", "3,30"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "consensus", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["abc", "def", "30"]


@needs_parquet
def test_consensus_ignores_parquet_precedence(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,20"])
    c = write_parquet(tmp_path / "c.parquet", {"id": [3], "v": ["x"]})
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "consensus", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "20", ""]


def test_consensus_half_the_files_is_not_a_majority(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,abc"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "consensus", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "abc"]


# --------------------------------------------------------------------------
# Phrase: "--schema-strategy=union: choose simplest common type that can hold
#          all observed values"
# Context: Schema disagreement strategy.
# --------------------------------------------------------------------------
def test_union_widens_int_and_float(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,2.5"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "union", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10.0", "2.5"]


def test_union_falls_back_to_string_when_nothing_else_holds(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,abc"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "union", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "abc"]


def test_union_keeps_the_narrow_type_when_all_agree(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 2, "v": 20}])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "union", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "20"]


def test_union_widens_date_and_timestamp(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,t", "1,2024-07-01"])
    b = write_csv(tmp_path / "b.csv", ["id,t", "2,2024-07-02T12:00:00Z"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "union", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "t") == ["2024-07-01T00:00:00Z",
                                    "2024-07-02T12:00:00Z"]


@needs_parquet
def test_union_ignores_parquet_precedence(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_parquet(tmp_path / "b.parquet", {"id": [2], "v": ["x"]})
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "union", a, b)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["10", "x"]


def test_schema_strategy_rejects_unknown_value(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id",
                   "--schema-strategy", "vote", a)
    assert res.returncode != 0


def test_schema_strategy_ignored_when_schema_given(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,10"])
    b = write_csv(tmp_path / "b.csv", ["id,v", "2,20"])
    outs = set()
    for strategy in ("authoritative", "consensus", "union"):
        res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                       "--schema-strategy", strategy, a, b)
        assert res.returncode == 0, res.stderr
        outs.add(res.stdout)
    assert len(outs) == 1
