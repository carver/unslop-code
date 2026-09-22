"""Recursive casting inside nested values, and the --on-type-error policies."""

from datetime import date, datetime, timedelta, timezone

import pyarrow as pa
import pytest

OFFSET = timezone(timedelta(hours=2))

# A struct whose fields exercise every primitive family.
TYPED_STRUCT = {
    "columns": [
        {"name": "id", "type": "int"},
        {
            "name": "v",
            "type": {
                "struct": {
                    "fields": [
                        {"name": "n", "type": "int"},
                        {"name": "f", "type": "float"},
                        {"name": "b", "type": "bool"},
                        {"name": "d", "type": "date"},
                        {"name": "t", "type": "timestamp"},
                    ]
                }
            },
        },
    ]
}

ARRAY_OF_INT = {
    "columns": [
        {"name": "id", "type": "int"},
        {"name": "v", "type": {"array": {"element": "int"}}},
    ]
}


# Spec: "Nested values cast recursively to declared types"
def test_struct_fields_cast_to_their_declared_types(run_cli, jsonl_file, json_file):
    row = {"id": 1, "v": {"n": "7", "f": "1.5", "b": "true", "d": "2024-03-04", "t": "2024-03-04 05:06:07"}}
    data = jsonl_file("a.jsonl", [row])
    schema = json_file("s.json", TYPED_STRUCT)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == (
        '{"n":7,"f":1.5,"b":true,"d":"2024-03-04","t":"2024-03-04T05:06:07Z"}'
    )


# Spec: "Primitive casting rules ... apply recursively inside nested values"
# bool accepts 1/0 exactly as it does for a flat column.
def test_primitive_bool_rules_apply_inside_nested(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": ["1", "0"]}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": {"array": {"element": "bool"}}},
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == "[true,false]"


# Spec: "temporal normalization ... apply recursively inside nested values"
def test_timestamp_offsets_normalize_inside_nested(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": ["2024-03-04T07:06:07+02:00"]}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": {"array": {"element": "timestamp"}}},
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '["2024-03-04T05:06:07Z"]'


# Spec: "null handling apply recursively inside nested values"
def test_null_elements_survive_inside_an_array(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1, None, 3]}])
    schema = json_file("s.json", ARRAY_OF_INT)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == "[1,null,3]"


# Spec: "On cast failure within nested structures: coerce-null: set field/element to JSON null"
def test_coerce_null_nulls_the_failing_element(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1, "abc", 3]}])
    schema = json_file("s.json", ARRAY_OF_INT)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "coerce-null", data
    )
    assert result.rows[1][1] == "[1,null,3]"


# Spec: "coerce-null: set field/element to JSON null" — a struct field, not the whole column
def test_coerce_null_keeps_the_sibling_fields(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"n": "x", "f": 1, "b": True, "d": None, "t": None}}])
    schema = json_file("s.json", TYPED_STRUCT)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "coerce-null", data
    )
    assert result.rows[1][1] == '{"n":null,"f":1.0,"b":true,"d":null,"t":null}'


# Spec: "keep-string: set to original unparsed JSON string or stringified form"
def test_keep_string_preserves_the_failing_element(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1, "abc", 3]}])
    schema = json_file("s.json", ARRAY_OF_INT)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "keep-string", data
    )
    assert result.rows[1][1] == '[1,"abc",3]'


# Spec: "keep-string: set to ... stringified form" (AMBIGUITIES T55)
def test_keep_string_stringifies_a_nested_value_in_a_primitive_slot(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [{"k": 1}]}])
    schema = json_file("s.json", ARRAY_OF_INT)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "keep-string", data
    )
    assert result.rows[1][1] == '["{\\"k\\":1}"]'


# Spec: 'fail: emit ERR 4 cannot cast "<val>" to <type> in field "<path>" (file=... line=...)'
def test_fail_reports_err_4_with_the_field_path(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"n": "abc"}}])
    schema = json_file("s.json", TYPED_STRUCT)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", data
    )
    assert result.returncode == 4
    assert "ERR 4" in result.stderr
    assert 'cannot cast "abc" to int' in result.stderr
    assert 'in field "v.n"' in result.stderr


# Spec: 'fail: emit ERR 4 ... (file=... line=...)'
def test_fail_message_names_the_file_and_line(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1]}, {"id": 2, "v": ["x"]}])
    schema = json_file("s.json", ARRAY_OF_INT)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", data
    )
    assert "file=" in result.stderr and "a.jsonl" in result.stderr
    assert "line=2" in result.stderr


# Spec: 'in field "<path>"' — array positions appear in the path
def test_fail_path_includes_the_array_index(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1, 2, "x"]}])
    schema = json_file("s.json", ARRAY_OF_INT)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", data
    )
    assert 'in field "v.2"' in result.stderr


# Spec: "For json type: accept any JSON value without casting; normalize only"
def test_json_type_does_not_cast_its_contents(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"n": "0007", "d": "2024-03-04", "b": "true"}}])
    schema = json_file(
        "s.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "json"}]},
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"b":"true","d":"2024-03-04","n":"0007"}'


# Spec: "For json type: accept any JSON value without casting" — never a cast failure
def test_json_type_never_fails_under_fail_policy(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [{"deep": [1, "two", None]}]}])
    schema = json_file(
        "s.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "json"}]},
    )
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", data
    )
    assert result.returncode == 0, result.stderr


# Spec: "Nested values cast recursively" — Parquet timestamps normalize inside a struct
def test_parquet_nested_temporal_values_normalize(run_cli, parquet_file, json_file):
    inner = pa.struct(
        [pa.field("d", pa.date32()), pa.field("t", pa.timestamp("us", tz="+02:00"))]
    )
    table = pa.table(
        {
            "id": pa.array([1], pa.int64()),
            "v": pa.array(
                [{"d": date(2024, 3, 4), "t": datetime(2024, 3, 4, 7, 6, 7, tzinfo=OFFSET)}], inner
            ),
        }
    )
    data = parquet_file("a.parquet", table)
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {
                    "name": "v",
                    "type": {
                        "struct": {
                            "fields": [
                                {"name": "d", "type": "date"},
                                {"name": "t", "type": "timestamp"},
                            ]
                        }
                    },
                },
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"d":"2024-03-04","t":"2024-03-04T05:06:07Z"}'


# Spec: "Nested values cast recursively to declared types" — map values too
@pytest.mark.parametrize("policy,expected", [("coerce-null", "null"), ("keep-string", '"x"')])
def test_map_value_cast_failures_follow_the_policy(run_cli, jsonl_file, json_file, policy, expected):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": "x"}}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": {"map": {"key": "string", "value": "int"}}},
            ]
        },
    )
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", policy, data
    )
    assert result.rows[1][1] == '{"a":%s}' % expected
