"""Schema resolution across CSV, TSV, JSONL and Parquet inputs."""

import json

import pytest


@pytest.fixture
def schema_file(tmp_path):
    def _write(columns, name="schema.json"):
        path = tmp_path / name
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    return _write


# --- Provided schema -------------------------------------------------------


def test_provided_schema_defines_columns_types_and_order(run_cli, csv_file, jsonl_file, schema_file):
    # Spec: "If `--schema` provided, it defines exact output columns, types, and order"
    schema = schema_file([{"name": "note", "type": "string"}, {"name": "id", "type": "int"}])
    a = csv_file("a.csv", "id,note\n1,x\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "note": "y"}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a, b)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["note", "id"], ["x", "1"], ["y", "2"]]


def test_provided_schema_ignores_extra_input_columns(run_cli, jsonl_file, parquet_file, schema_file):
    # Spec: "Extra input columns ignored"
    schema = schema_file([{"name": "id", "type": "int"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "extra": "drop"}])
    b = parquet_file("b.parquet", {"id": [2], "other": ["drop"]})
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a, b)
    assert result.rows == [["id"], ["1"], ["2"]]


def test_provided_schema_fills_missing_columns_with_null_literal(run_cli, jsonl_file, schema_file):
    # Spec: "missing columns filled with null literal"
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "note", "type": "string"}])
    a = jsonl_file("a.jsonl", [{"id": 1}])
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, "--csv-null-literal", "NA", a)
    assert result.rows == [["id", "note"], ["1", "NA"]]


# --- Inferred column set and order -----------------------------------------


def test_inferred_column_set_is_union_of_all_field_names(run_cli, csv_file, jsonl_file, parquet_file):
    # Spec: "Column set: union of all encountered field names"
    a = csv_file("a.csv", "id,fromcsv\n1,x\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "fromjson": "y"}])
    c = parquet_file("c.parquet", {"id": [3], "fromparquet": ["z"]})
    result = run_cli("--output", "-", "--key", "id", a, b, c)
    assert result.returncode == 0, result.stderr
    assert result.rows[0] == ["fromcsv", "fromjson", "fromparquet", "id"]


def test_inferred_column_order_is_ascending_lexicographic(run_cli, csv_file, jsonl_file):
    # Spec: "Column order: ascending lexicographic by column name"
    a = csv_file("a.csv", "zeta,Beta,alpha\n1,2,3\n")
    b = jsonl_file("b.jsonl", [{"Alpha": 4}])
    result = run_cli("--output", "-", "--key", "alpha", a, b)
    assert result.rows[0] == ["Alpha", "Beta", "alpha", "zeta"]


def test_header_only_source_still_contributes_columns(run_cli, csv_file, jsonl_file):
    # Spec: "union of all encountered field names" (AMBIGUITIES T32)
    a = csv_file("a.csv", "id,ghost\n")
    b = jsonl_file("b.jsonl", [{"id": 1}])
    result = run_cli("--output", "-", "--key", "id", a, b)
    assert result.rows == [["ghost", "id"], ["", "1"]]


def test_parquet_schema_types_are_used_for_inference(run_cli, parquet_file):
    # Spec: "Parquet values come typed" + "Type inference per `--infer` mode"
    import datetime as dt

    a = parquet_file(
        "a.parquet",
        {
            "d": [dt.date(2024, 7, 1)],
            "f": [2.5],
            "flag": [True],
            "n": [7],
            "ts": [dt.datetime(2024, 7, 1, 12, 0, 0)],
        },
    )
    result = run_cli("--output", "-", "--key", "n", a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [
        ["d", "f", "flag", "n", "ts"],
        ["2024-07-01", "2.5", "True", "7", "2024-07-01T12:00:00Z"],
    ]


# --- Disagreement strategies -----------------------------------------------


def test_authoritative_prefers_typed_source_over_text(run_cli, csv_file, jsonl_file):
    # Spec: "`--schema-strategy=authoritative` (default): prefer typed sources in precedence order"
    a = csv_file("a.csv", "id,amount\n1,5\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "amount": 2.5}])
    result = run_cli("--output", "-", "--key", "id", a, b)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["amount", "id"], ["5.0", "1"], ["2.5", "2"]]


def test_authoritative_prefers_parquet_over_jsonl(run_cli, jsonl_file, parquet_file):
    # Spec: "prefer typed sources in precedence order" (AMBIGUITIES T19: parquet > jsonl > text)
    a = jsonl_file("a.jsonl", [{"id": 1, "code": 7}])
    b = parquet_file("b.parquet", {"id": [2], "code": ["abc"]})
    result = run_cli("--output", "-", "--key", "id", a, b)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["code", "id"], ["7", "1"], ["abc", "2"]]


def test_authoritative_is_the_default_strategy(run_cli, csv_file, jsonl_file):
    # Spec: "`--schema-strategy=authoritative` (default)"
    a = csv_file("a.csv", "id,amount\n1,5\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "amount": 2.5}])
    explicit = run_cli("--output", "-", "--key", "id", "--schema-strategy", "authoritative", a, b)
    assert explicit.stdout == run_cli("--output", "-", "--key", "id", a, b).stdout


def test_authoritative_falls_back_to_string_inside_a_tier(run_cli, csv_file):
    # Spec: "conflicting types for same column" within one precedence tier (AMBIGUITIES T20)
    a = csv_file("a.csv", "id,amount\n7,5\n")
    b = csv_file("b.csv", "id,amount\n8,2.5\n")
    result = run_cli("--output", "-", "--key", "id", "--infer", "strict", a, b)
    assert result.rows == [["amount", "id"], ["5", "7"], ["2.5", "8"]]


def test_loose_infer_widens_inside_a_tier(run_cli, csv_file):
    # Spec: "Type inference per `--infer` mode (strict or loose)"
    a = csv_file("a.csv", "id,amount\n7,5\n")
    b = csv_file("b.csv", "id,amount\n8,2.5\n")
    result = run_cli("--output", "-", "--key", "id", "--infer", "loose", a, b)
    assert result.rows == [["amount", "id"], ["5.0", "7"], ["2.5", "8"]]


def test_consensus_picks_the_majority_supported_type(run_cli, csv_file, jsonl_file):
    # Spec: "`--schema-strategy=consensus`: choose type that majority of files support"
    a = csv_file("a.csv", "id,amount\n1,5\n")
    b = csv_file("b.csv", "id,amount\n2,6\n")
    c = jsonl_file("c.jsonl", [{"id": 3, "amount": 2.5}])
    result = run_cli("--output", "-", "--key", "id", "--schema-strategy", "consensus", a, b, c)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["amount", "id"], ["5", "1"], ["6", "2"], ["", "3"]]


def test_consensus_without_a_majority_widens(run_cli, csv_file):
    # Spec: "choose type that majority of files support" (AMBIGUITIES T21: support, not votes)
    files = [
        csv_file("a.csv", "id,amount\n1,5\n"),
        csv_file("b.csv", "id,amount\n2,6\n"),
        csv_file("c.csv", "id,amount\n3,2.5\n"),
        csv_file("d.csv", "id,amount\n4,3.5\n"),
    ]
    result = run_cli("--output", "-", "--key", "id", "--schema-strategy", "consensus", *files)
    assert result.rows[1:] == [["5.0", "1"], ["6.0", "2"], ["2.5", "3"], ["3.5", "4"]]


def test_consensus_outvoted_values_follow_the_type_error_policy(run_cli, csv_file):
    # Spec: consensus type + "On cast failure, follow `--on-type-error`"
    a = csv_file("a.csv", "id,amount\n1,5\n")
    b = csv_file("b.csv", "id,amount\n2,6\n")
    c = csv_file("c.csv", "id,amount\n3,oops\n")
    result = run_cli(
        "--output", "-", "--key", "id", "--schema-strategy", "consensus",
        "--on-type-error", "keep-string", a, b, c,
    )
    assert result.rows == [["amount", "id"], ["5", "1"], ["6", "2"], ["oops", "3"]]


def test_union_picks_simplest_type_holding_all_values(run_cli, csv_file, jsonl_file):
    # Spec: "`--schema-strategy=union`: choose simplest common type that can hold all observed values"
    a = csv_file("a.csv", "id,amount\n1,5\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "amount": 2.5}])
    result = run_cli("--output", "-", "--key", "id", "--schema-strategy", "union", a, b)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["amount", "id"], ["5.0", "1"], ["2.5", "2"]]


def test_union_falls_back_to_string_when_no_numeric_type_holds_all(run_cli, csv_file):
    # Spec: "simplest common type that can hold all observed values"
    a = csv_file("a.csv", "id,amount\n1,5\n")
    b = csv_file("b.csv", "id,amount\n2,abc\n")
    result = run_cli("--output", "-", "--key", "id", "--schema-strategy", "union", a, b)
    assert result.rows == [["amount", "id"], ["5", "1"], ["abc", "2"]]


def test_union_beats_strict_conflict_fallback(run_cli, csv_file):
    # Spec: union reconciles conflicts instead of falling back to `string`
    a = csv_file("a.csv", "id,amount\n1,5\n")
    b = csv_file("b.csv", "id,amount\n2,2.5\n")
    strict = run_cli("--output", "-", "--key", "id", a, b)
    union = run_cli("--output", "-", "--key", "id", "--schema-strategy", "union", a, b)
    assert strict.rows[1] == ["5", "1"]
    assert union.rows[1] == ["5.0", "1"]


def test_schema_strategy_rejects_unknown_value(run_cli, csv_file):
    # Spec usage: "[--schema-strategy {authoritative,consensus,union}]"
    a = csv_file("a.csv", "id\n1\n")
    assert run_cli("--output", "-", "--key", "id", "--schema-strategy", "nope", a).returncode != 0
