"""Schema resolution: explicit `--schema` files and inferred schemas."""

import json

import pytest


@pytest.fixture
def schema_file(tmp_path):
    def _write(columns, name="schema.json"):
        path = tmp_path / name
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    return _write


def test_schema_file_gives_exact_columns_order_and_types(run_cli, csv_file, schema_file):
    # Spec: "If `--schema` is provided: JSON file with exact output schema and column order"
    schema = schema_file(
        [
            {"name": "id", "type": "int"},
            {"name": "ts", "type": "timestamp"},
            {"name": "amount", "type": "float"},
            {"name": "note", "type": "string"},
            {"name": "is_active", "type": "bool"},
        ]
    )
    a = csv_file("a.csv", "note,id,is_active,amount,ts\nx,7,1,2.5,2024-07-01T12:00:00Z\n")
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.returncode == 0, result.stderr
    assert result.rows == [
        ["id", "ts", "amount", "note", "is_active"],
        ["7", "2024-07-01T12:00:00Z", "2.5", "x", "True"],
    ]


def test_extra_input_columns_are_ignored(run_cli, csv_file, schema_file):
    # Spec: "Extra input columns not in schema are ignored"
    schema = schema_file([{"name": "id", "type": "int"}])
    a = csv_file("a.csv", "id,extra\n7,dropme\n")
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.rows == [["id"], ["7"]]


def test_missing_input_columns_filled_with_null_literal(run_cli, csv_file, schema_file):
    # Spec: "Missing input columns filled with null literal"
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "note", "type": "string"}])
    a = csv_file("a.csv", "id\n7\n")
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, "--csv-null-literal", "-", a)
    assert result.rows == [["id", "note"], ["7", "-"]]


def test_unknown_schema_type_is_an_error(run_cli, csv_file, schema_file):
    # Spec: "Valid types: `string`, `int`, `float`, `bool`, `date`, `timestamp`"
    schema = schema_file([{"name": "id", "type": "decimal"}])
    a = csv_file("a.csv", "id\n7\n")
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.returncode != 0
    assert "decimal" in result.stderr


def test_inferred_columns_are_union_of_headers_in_lexicographic_order(run_cli, csv_file):
    # Spec: "infer schema from union of all input headers" /
    #       "Column order: ascending lexicographic order of column names"
    a = csv_file("a.csv", "beta,alpha\n1,x\n")
    b = csv_file("b.csv", "delta,alpha\n2,y\n")
    result = run_cli("--output", "-", "--key", "alpha", a, b)
    assert result.rows[0] == ["alpha", "beta", "delta"]


def test_missing_columns_in_a_file_are_null(run_cli, csv_file):
    # Spec: "Missing columns in a file filled with null literal"
    a = csv_file("a.csv", "alpha,beta\nx,9\n")
    b = csv_file("b.csv", "alpha\ny\n")
    result = run_cli("--output", "-", "--key", "alpha", "--csv-null-literal", "NA", a, b)
    assert result.rows == [["alpha", "beta"], ["x", "9"], ["y", "NA"]]


def test_strict_infers_type_from_observed_values(run_cli, csv_file):
    # Spec: "strict (default): infer types based on observed values"
    a = csv_file("a.csv", "k,n\na,007\nb,20\n")
    result = run_cli("--output", "-", "--key", "k", a)
    # int cast then rendered: leading zeros are dropped (AMBIGUITIES T9)
    assert result.rows == [["k", "n"], ["a", "7"], ["b", "20"]]


def test_strict_conflicting_types_across_files_fall_back_to_string(run_cli, csv_file):
    # Spec: "columns with conflicting types across files fall back to `string`"
    a = csv_file("a.csv", "k,n\na,20\n")
    b = csv_file("b.csv", "k,n\nb,hello\n")
    result = run_cli("--output", "-", "--key", "k", a, b)
    assert result.rows == [["k", "n"], ["a", "20"], ["b", "hello"]]


def test_strict_int_and_float_across_files_conflict(run_cli, csv_file):
    # Spec: "columns with conflicting types across files fall back to `string`" (AMBIGUITIES T3)
    a = csv_file("a.csv", "k,n\na,20\n")
    b = csv_file("b.csv", "k,n\nb,1.50\n")
    result = run_cli("--output", "-", "--key", "k", a, b)
    assert result.rows == [["k", "n"], ["a", "20"], ["b", "1.50"]]


def test_loose_widens_int_and_float_to_float(run_cli, csv_file):
    # Spec: "loose: prefer numeric/temporal types if all non-null observed values parse"
    a = csv_file("a.csv", "k,n\na,20\n")
    b = csv_file("b.csv", "k,n\nb,1.50\n")
    result = run_cli("--output", "-", "--key", "k", "--infer", "loose", a, b)
    assert result.rows == [["k", "n"], ["a", "20.0"], ["b", "1.5"]]


def test_loose_falls_back_to_string_when_a_value_does_not_parse(run_cli, csv_file):
    # Spec: "otherwise fall back to `string`"
    a = csv_file("a.csv", "k,n\na,20\nb,nope\n")
    result = run_cli("--output", "-", "--key", "k", "--infer", "loose", a)
    assert result.rows == [["k", "n"], ["a", "20"], ["b", "nope"]]


def test_loose_ignores_empty_strings_when_inferring(run_cli, csv_file):
    # Spec: "empty strings are treated as nulls and don't affect inference"
    a = csv_file("a.csv", "k,n\na,\nb,1.50\n")
    result = run_cli("--output", "-", "--key", "k", "--infer", "loose", a)
    assert result.rows == [["k", "n"], ["a", ""], ["b", "1.5"]]


def test_strict_also_ignores_empty_strings_when_inferring(run_cli, csv_file):
    # Spec: "empty strings are treated as nulls" applied to strict as well (AMBIGUITIES T2)
    a = csv_file("a.csv", "k,n\na,\nb,1.50\n")
    result = run_cli("--output", "-", "--key", "k", a)
    assert result.rows == [["k", "n"], ["a", ""], ["b", "1.5"]]


def test_column_with_only_nulls_infers_string(run_cli, csv_file):
    # Spec: "otherwise fall back to `string`" with nothing observed (AMBIGUITIES T14)
    a = csv_file("a.csv", "k,n\na,\n")
    result = run_cli("--output", "-", "--key", "k", a)
    assert result.rows == [["k", "n"], ["a", ""]]


def test_priority_prefers_int_over_float(run_cli, csv_file):
    # Spec: "Type priority: timestamp > date > bool > int > float > string"
    a = csv_file("a.csv", "k,n\na,20\nb,31\n")
    result = run_cli("--output", "-", "--key", "k", a)
    assert result.rows == [["k", "n"], ["a", "20"], ["b", "31"]]


def test_priority_prefers_bool_over_int_for_zero_and_one(run_cli, csv_file):
    # Spec: "Type priority: ... bool > int" with "bool includes 1/0" (AMBIGUITIES T5)
    a = csv_file("a.csv", "k,flag\na,1\nb,0\n")
    result = run_cli("--output", "-", "--key", "k", a)
    assert result.rows == [["flag", "k"], ["True", "a"], ["False", "b"]]


def test_date_only_values_infer_as_date(run_cli, csv_file):
    # Spec: "date: ISO-8601 YYYY-MM-DD" reachable under the priority list (AMBIGUITIES T4)
    a = csv_file("a.csv", "k,d\na,2024-07-01\n")
    result = run_cli("--output", "-", "--key", "k", a)
    assert result.rows == [["d", "k"], ["2024-07-01", "a"]]


def test_values_with_time_component_infer_as_timestamp(run_cli, csv_file):
    # Spec: "Type priority: timestamp > date" / "normalize to UTC with Z suffix in output"
    a = csv_file("a.csv", "k,t\na,2024-07-01T14:00:00+02:00\n")
    result = run_cli("--output", "-", "--key", "k", a)
    assert result.rows == [["k", "t"], ["a", "2024-07-01T12:00:00Z"]]


def test_infer_flag_is_ignored_when_schema_is_given(run_cli, csv_file, schema_file):
    # Spec: schema resolution is either the provided schema or inference, never both
    schema = schema_file([{"name": "n", "type": "string"}])
    a = csv_file("a.csv", "n\n1.50\n")
    result = run_cli("--output", "-", "--key", "n", "--schema", schema, "--infer", "loose", a)
    assert result.rows == [["n"], ["1.50"]]
