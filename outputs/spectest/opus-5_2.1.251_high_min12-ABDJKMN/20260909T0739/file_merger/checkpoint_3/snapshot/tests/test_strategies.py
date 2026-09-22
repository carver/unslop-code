"""`Schema Resolution Across Heterogeneous Inputs`."""
from conftest import (merge_paths, pa_modules, write, write_jsonl,
                      write_parquet, write_schema)


# --- Spec: "If --schema provided, it defines exact output columns, types,
#            and order" ----------------------------------------------------
def test_provided_schema_defines_columns_types_and_order(tmp_path):
    schema = write_schema(tmp_path, "s.json",
                          [("name", "string"), ("id", "int")])
    c = write(tmp_path, "a.csv", "id,name\n1,c\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "name": "j"}])
    r = merge_paths([c, j], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows() == [["name", "id"], ["c", "1"], ["j", "2"]]


# --- Spec: "Extra input columns ignored; missing columns filled with null
#            literal" -----------------------------------------------------
def test_provided_schema_ignores_extras_and_fills_missing(tmp_path):
    schema = write_schema(tmp_path, "s.json",
                          [("id", "int"), ("absent", "string")])
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "extra": "e"}])
    r = merge_paths([j], "--key", "id", "--schema", str(schema),
                    "--csv-null-literal", "-")
    assert r.ok, r
    assert r.rows() == [["id", "absent"], ["2", "-"]]


# --- Spec: "If --schema not provided ... Column set: union of all
#            encountered field names" -------------------------------------
def test_inferred_column_set_is_the_union(tmp_path):
    c = write(tmp_path, "a.csv", "id,c_only\n1,x\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "j_only": "y"}])
    p = write_parquet(tmp_path, "c.parquet", [{"id": 3, "p_only": "z"}])
    r = merge_paths([c, j, p], "--key", "id")
    assert r.ok, r
    assert r.rows()[0] == ["c_only", "id", "j_only", "p_only"]


# --- Spec: "Column order: ascending lexicographic by column name" ---------
def test_inferred_column_order_is_lexicographic(tmp_path):
    j = write_jsonl(tmp_path, "b.jsonl", [{"zeta": 1, "Alpha": 2, "mid": 3}])
    r = merge_paths([j], "--key", "mid")
    assert r.ok, r
    assert r.rows()[0] == ["Alpha", "mid", "zeta"]


# --- Spec: "Type inference per --infer mode (strict or loose)" ------------
def test_infer_mode_still_applies_to_mixed_inputs(tmp_path):
    c = write(tmp_path, "a.csv", "id,v\n1,3\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "v": 4}])
    r = merge_paths([c, j], "--key", "id", "--infer", "loose")
    assert r.ok, r
    assert r.rows()[1:] == [["1", "3"], ["2", "4"]]


# --- Spec: "--schema-strategy=authoritative (default): prefer typed sources
#            in precedence order" ------------------------------------------
def test_authoritative_prefers_typed_source_over_text(tmp_path):
    # Text says int; the typed JSONL source says float, and wins.
    c = write(tmp_path, "a.csv", "id,v\n1,7\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "v": 2.5}])
    r = merge_paths([c, j], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["1", "7.0"]
    assert r.rows()[2] == ["2", "2.5"]


def test_authoritative_is_the_default(tmp_path):
    c = write(tmp_path, "a.csv", "id,v\n1,7\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "v": 2.5}])
    explicit = merge_paths([c, j], "--key", "id",
                           "--schema-strategy", "authoritative")
    default = merge_paths([c, j], "--key", "id")
    assert explicit.ok and default.ok
    assert explicit.stdout == default.stdout


def test_authoritative_prefers_parquet_over_jsonl(tmp_path):
    pa, _ = pa_modules()
    schema = pa.schema([("id", pa.int64()), ("v", pa.string())])
    p = write_parquet(tmp_path, "a.parquet", [{"id": 1, "v": "01"}],
                      schema=schema)
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "v": 5}])
    r = merge_paths([p, j], "--key", "id")
    assert r.ok, r
    # Parquet outranks JSONL, so `v` is a string and "01" keeps its zero.
    assert r.rows()[1] == ["1", "01"]
    assert r.rows()[2] == ["2", "5"]


# --- Spec: "--schema-strategy=consensus: choose type that majority of files
#            support" ------------------------------------------------------
def test_consensus_follows_the_majority_of_files(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,10\n")
    b = write(tmp_path, "b.csv", "id,v\n2,20\n")
    j = write_jsonl(tmp_path, "c.jsonl", [{"id": 3, "v": 2.5}])
    r = merge_paths([a, b, j], "--key", "id",
                    "--schema-strategy", "consensus")
    assert r.ok, r
    # Two of three files say int, so `v` is int and 2.5 fails the cast.
    assert r.rows()[1] == ["1", "10"]
    assert r.rows()[2] == ["2", "20"]
    assert r.rows()[3] == ["3", ""]


def test_consensus_differs_from_authoritative(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,10\n")
    b = write(tmp_path, "b.csv", "id,v\n2,20\n")
    j = write_jsonl(tmp_path, "c.jsonl", [{"id": 3, "v": 2.5}])
    auth = merge_paths([a, b, j], "--key", "id")
    cons = merge_paths([a, b, j], "--key", "id",
                       "--schema-strategy", "consensus")
    assert auth.ok and cons.ok
    assert auth.stdout != cons.stdout


# --- Spec: "consensus" with no majority - ties resolve by the checkpoint 1
#            type priority (timestamp > date > bool > int > float > string)
def test_consensus_tie_broken_by_type_priority(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,true\n3,false\n")
    b = write(tmp_path, "b.csv", "id,v\n2,5\n4,6\n")
    r = merge_paths([a, b], "--key", "id", "--schema-strategy", "consensus")
    assert r.ok, r
    # One file says bool, one says int: bool outranks int, so `5` and `6`
    # no longer cast.
    assert [row[1] for row in r.rows()[1:]] == ["true", "", "false", ""]


# --- Spec: "--schema-strategy=union: choose simplest common type that can
#            hold all observed values" -------------------------------------
def test_union_widens_int_and_float_to_float(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,10\n")
    b = write(tmp_path, "b.csv", "id,v\n2,20\n")
    j = write_jsonl(tmp_path, "c.jsonl", [{"id": 3, "v": 2.5}])
    r = merge_paths([a, b, j], "--key", "id", "--schema-strategy", "union")
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["10.0", "20.0", "2.5"]


def test_union_falls_back_to_string_when_nothing_else_holds(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,10\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "v": "abc"}])
    r = merge_paths([a, j], "--key", "id", "--schema-strategy", "union")
    assert r.ok, r
    assert [row[1] for row in r.rows()[1:]] == ["10", "abc"]


# --- Spec: "--schema-strategy {authoritative,consensus,union}" - unknown
#            values are rejected ------------------------------------------
def test_unknown_strategy_rejected(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = merge_paths([a], "--key", "id", "--schema-strategy", "vote")
    assert r.returncode == 2, r


# --- Spec: "If --schema provided, it defines exact output columns" - the
#            strategy is irrelevant then ----------------------------------
def test_strategy_ignored_when_schema_given(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "float")])
    a = write(tmp_path, "a.csv", "id,v\n1,10\n")
    j = write_jsonl(tmp_path, "b.jsonl", [{"id": 2, "v": 2.5}])
    outs = set()
    for strategy in ("authoritative", "consensus", "union"):
        r = merge_paths([a, j], "--key", "id", "--schema", str(schema),
                        "--schema-strategy", strategy)
        assert r.ok, r
        outs.add(r.stdout)
    assert len(outs) == 1
    assert list(outs)[0].splitlines()[1:] == ["1,10.0", "2,2.5"]
