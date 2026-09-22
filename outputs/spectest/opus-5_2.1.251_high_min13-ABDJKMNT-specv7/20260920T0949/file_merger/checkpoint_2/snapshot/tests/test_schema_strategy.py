"""Schema reconciliation across inputs that disagree about a column's type."""

import pyarrow as pa

from conftest import rows_of


# Spec: "If `--schema` provided, it defines exact output columns, types, and order"
# Context: a provided schema settles the disagreement before any strategy applies.
def test_provided_schema_overrides_every_strategy(make_csv, make_jsonl, make_schema, run):
    make_csv("a.csv", "id,v\n1,7\n")
    make_jsonl("b.jsonl", [{"id": 2, "v": "9"}])
    make_schema("s.json", [("v", "string"), ("id", "int")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--schema-strategy", "consensus", "a.csv", "b.jsonl")
    assert rows_of(proc.stdout) == [["v", "id"], ["7", "1"], ["9", "2"]]


# Spec: "Column set: union of all encountered field names"
def test_column_set_is_the_union_across_formats(make_csv, make_jsonl, make_parquet, run):
    make_csv("a.csv", "id,c\n1,x\n")
    make_jsonl("b.jsonl", [{"id": 2, "j": "y"}])
    make_parquet("c.parquet", {"id": pa.array([3]), "p": pa.array(["z"])})
    proc = run("--output", "-", "--key", "id", "a.csv", "b.jsonl", "c.parquet")
    assert rows_of(proc.stdout)[0] == ["c", "id", "j", "p"]


# Spec: "Column order: ascending lexicographic by column name"
def test_inferred_column_order_is_lexicographic(make_jsonl, run):
    make_jsonl("a.jsonl", [{"zeta": 1, "Alpha": 2, "beta": 3}])
    proc = run("--output", "-", "--key", "zeta", "a.jsonl")
    assert rows_of(proc.stdout)[0] == ["Alpha", "beta", "zeta"]


# Spec: "--schema-strategy=authoritative (default): prefer typed sources in precedence order"
# Context: see AMBIGUITIES T28 - parquet is the typed source, so its declared
# int type wins over a CSV column whose values are fractional.
def test_authoritative_prefers_the_parquet_declared_type(make_csv, make_parquet, run):
    make_csv("a.csv", "v\n9.5\n")
    make_parquet("b.parquet", {"v": pa.array([10], pa.int64())})
    proc = run("--output", "-", "--key", "v", "a.csv", "b.parquet")
    # 9.5 does not fit the int column and is coerced to null, which sorts first
    assert rows_of(proc.stdout)[1:] == [[""], ["10"]]


# Spec: "--schema-strategy=authoritative (default)"
def test_authoritative_is_the_default(make_csv, make_parquet, run):
    make_csv("a.csv", "v\n9.5\n")
    make_parquet("b.parquet", {"v": pa.array([10], pa.int64())})
    implicit = run("--output", "-", "--key", "v", "a.csv", "b.parquet").stdout
    explicit = run("--output", "-", "--key", "v", "--schema-strategy", "authoritative", "a.csv", "b.parquet").stdout
    assert implicit == explicit


# Spec: "prefer typed sources in precedence order; JSONL ranks equal to CSV"
# Context: see AMBIGUITIES T28 - JSONL does not outrank CSV, so their
# disagreement falls back to the plain --infer rule (strict: string).
def test_jsonl_does_not_outrank_csv(make_csv, make_jsonl, run):
    make_csv("a.csv", "v\n9.5\n")
    make_jsonl("b.jsonl", [{"v": 10}])
    proc = run("--output", "-", "--key", "v", "a.csv", "b.jsonl")
    assert rows_of(proc.stdout)[1:] == [["10"], ["9.5"]]


# Spec: "prefer typed sources in precedence order" with "[--infer {strict,loose}]"
# Context: below the parquet tier the inference mode still decides; loose widens.
def test_infer_mode_still_applies_below_the_typed_tier(make_csv, make_jsonl, run):
    make_csv("a.csv", "v\n9.5\n")
    make_jsonl("b.jsonl", [{"v": 10}])
    proc = run("--output", "-", "--key", "v", "--infer", "loose", "a.csv", "b.jsonl")
    assert rows_of(proc.stdout)[1:] == [["9.5"], ["10.0"]]


# Spec: "--schema-strategy=consensus: choose type that majority of files support"
# Context: see AMBIGUITIES T29 - two int files outvote one text file.
def test_consensus_follows_the_majority_of_files(make_csv, run):
    make_csv("a.csv", "v\n5\n")
    make_csv("b.csv", "v\n7\n")
    make_csv("c.csv", "v\nabc\n")
    proc = run("--output", "-", "--key", "v", "--schema-strategy", "consensus", "a.csv", "b.csv", "c.csv")
    # an int column: the outvoted text value is coerced to null and sorts first
    assert rows_of(proc.stdout)[1:] == [[""], ["5"], ["7"]]


# Spec: "--schema-strategy=consensus: choose type that majority of files support"
# Context: the same inputs under the default strategy fall back to string.
def test_consensus_differs_from_authoritative(make_csv, run):
    make_csv("a.csv", "v\n5\n")
    make_csv("b.csv", "v\n7\n")
    make_csv("c.csv", "v\nabc\n")
    consensus = run("--output", "-", "--key", "v", "--schema-strategy", "consensus", "a.csv", "b.csv", "c.csv").stdout
    authoritative = run("--output", "-", "--key", "v", "a.csv", "b.csv", "c.csv").stdout
    assert consensus != authoritative
    assert rows_of(authoritative)[1:] == [["5"], ["7"], ["abc"]]


# Spec: "--schema-strategy=union: choose simplest common type that can hold all observed values"
# Context: see AMBIGUITIES T30 - int and float observations are held by float.
def test_union_widens_int_and_float_to_float(make_csv, run):
    make_csv("a.csv", "v\n5\n")
    make_csv("b.csv", "v\n2.5\n")
    proc = run("--output", "-", "--key", "v", "--schema-strategy", "union", "a.csv", "b.csv")
    assert rows_of(proc.stdout)[1:] == [["2.5"], ["5.0"]]


# Spec: "--schema-strategy=union: choose simplest common type that can hold all observed values"
# Context: when nothing narrower holds every value, string does.
def test_union_falls_back_to_string_when_no_narrow_type_holds(make_csv, run):
    make_csv("a.csv", "v\n5\n")
    make_csv("b.csv", "v\nabc\n")
    proc = run("--output", "-", "--key", "v", "--schema-strategy", "union", "a.csv", "b.csv")
    assert rows_of(proc.stdout)[1:] == [["5"], ["abc"]]


# Spec: "--schema-strategy=union" across formats
# Context: a parquet int column and a JSONL fractional number widen to float.
def test_union_widens_across_formats(make_parquet, make_jsonl, run):
    make_parquet("a.parquet", {"v": pa.array([5], pa.int64())})
    make_jsonl("b.jsonl", [{"v": 2.5}])
    proc = run("--output", "-", "--key", "v", "--schema-strategy", "union", "a.parquet", "b.jsonl")
    assert rows_of(proc.stdout)[1:] == [["2.5"], ["5.0"]]


# Spec: "[--schema-strategy {authoritative,consensus,union}]"
def test_schema_strategy_is_restricted_to_listed_choices(make_csv, run):
    make_csv("a.csv", "v\n1\n")
    proc = run("--output", "-", "--key", "v", "--schema-strategy", "vote", "a.csv", expect_ok=False)
    assert proc.returncode == 2


# Spec: "Schema disagreement strategy when inputs have conflicting types for same column"
# Context: a column every file agrees on is unaffected by the strategy.
def test_agreeing_columns_are_unaffected_by_the_strategy(make_csv, run):
    make_csv("a.csv", "v\n5\n")
    make_csv("b.csv", "v\n7\n")
    outputs = {
        run("--output", "-", "--key", "v", "--schema-strategy", name, "a.csv", "b.csv").stdout
        for name in ("authoritative", "consensus", "union")
    }
    assert outputs == {"v\n5\n7\n"}


# Spec: "Keys must exist in resolved schema (error 3 otherwise)"
def test_key_outside_the_resolved_schema_exits_3(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 1}])
    proc = run("--output", "-", "--key", "missing", "a.jsonl", expect_ok=False)
    assert proc.returncode == 3
    assert proc.stderr.strip()


# Spec: "Keys must exist in resolved schema (error 3 otherwise)"
# Context: the resolved schema is the provided one, not the input's columns.
def test_key_present_in_input_but_not_in_provided_schema_exits_3(make_csv, make_schema, run):
    make_csv("a.csv", "id,v\n1,2\n")
    make_schema("s.json", [("id", "int")])
    proc = run("--output", "-", "--key", "v", "--schema", "s.json", "a.csv", expect_ok=False)
    assert proc.returncode == 3
