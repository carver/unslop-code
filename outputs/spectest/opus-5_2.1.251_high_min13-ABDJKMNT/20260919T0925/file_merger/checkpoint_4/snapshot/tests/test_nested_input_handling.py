"""Reading nested values out of JSONL, Parquet and delimited text."""

import pyarrow as pa
import pytest

STRUCT_SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {
            "name": "v",
            "type": {
                "struct": {
                    "fields": [{"name": "a", "type": "int"}, {"name": "b", "type": "string"}]
                }
            },
        },
    ]
}


def flat_schema(type_name="int"):
    return {"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": type_name}]}


# Spec: "JSONL: Accept nested objects/arrays only when schema declares column as nested"
def test_jsonl_object_accepted_for_struct_column(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1, "b": "x"}}])
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", '{"a":1,"b":"x"}']


# Spec: "JSONL: Accept nested objects/arrays only when schema declares column as ... json"
def test_jsonl_array_accepted_for_json_column(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [1, {"k": "v"}]}])
    schema = json_file("s.json", flat_schema("json"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", '[1,{"k":"v"}]']


# Spec: "If schema declares flat type but input has object/array, handle per --on-type-error"
def test_jsonl_object_into_flat_column_coerces_to_null(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    schema = json_file("s.json", flat_schema("int"))
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "coerce-null", data
    )
    assert result.rows[1] == ["1", ""]


# Spec: "If schema declares flat type but input has object/array, handle per --on-type-error"
def test_jsonl_object_into_flat_column_keeps_string(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    schema = json_file("s.json", flat_schema("int"))
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "keep-string", data
    )
    assert result.rows[1] == ["1", '{"a":1}']


# Spec: "If schema declares flat type but input has object/array, handle per --on-type-error"
# AMBIGUITIES T50: a `string` column is a flat type too, so this is still a cast error.
def test_jsonl_object_into_string_column_follows_the_policy(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    schema = json_file("s.json", flat_schema("string"))
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", data
    )
    assert result.returncode == 4, result.stderr


# Spec: "Parquet: Accept nested structs/lists/maps only when schema declares compatible nested types"
def test_parquet_struct_column(run_cli, parquet_file, json_file):
    table = pa.table(
        {
            "id": pa.array([1], pa.int64()),
            "v": pa.array(
                [{"a": 1, "b": "x"}],
                pa.struct([pa.field("a", pa.int64()), pa.field("b", pa.string())]),
            ),
        }
    )
    data = parquet_file("a.parquet", table)
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", '{"a":1,"b":"x"}']


# Spec: "Parquet: Accept nested ... lists ... only when schema declares compatible nested types"
def test_parquet_list_column(run_cli, parquet_file, json_file):
    table = pa.table({"id": pa.array([1], pa.int64()), "v": pa.array([[1, 2, 3]], pa.list_(pa.int64()))})
    data = parquet_file("a.parquet", table)
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": {"array": {"element": "int"}}},
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", "[1,2,3]"]


# Spec: "Parquet: Accept nested ... maps only when schema declares compatible nested types"
def test_parquet_map_column(run_cli, parquet_file, json_file):
    table = pa.table(
        {
            "id": pa.array([1], pa.int64()),
            "v": pa.array([[("b", 2), ("a", 1)]], pa.map_(pa.string(), pa.int64())),
        }
    )
    data = parquet_file("a.parquet", table)
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": {"map": {"key": "string", "value": "int"}}},
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", '{"a":1,"b":2}']


# Spec: "Parquet ... Without schema, nested triggers error 6"
def test_parquet_nested_without_schema_is_error_6(run_cli, parquet_file):
    table = pa.table(
        {"id": pa.array([1], pa.int64()), "v": pa.array([[1]], pa.list_(pa.int64()))}
    )
    data = parquet_file("a.parquet", table)
    result = run_cli("--output", "-", "--key", "id", data)
    assert result.returncode == 6, result.stderr


# Spec: "CSV/TSV: Cell must contain single JSON literal when target type is nested or json"
def test_csv_cell_holding_a_json_literal(run_cli, csv_file, json_file):
    data = csv_file("a.csv", 'id,v\n1,"{""a"": 1, ""b"": ""x""}"\n')
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", '{"a":1,"b":"x"}']


# Spec: the second example — arbitrary JSON in a column while sorting by a primitive, from TSV
def test_tsv_cell_holding_a_json_literal(run_cli, text_file, json_file):
    data = text_file("a.tsv", 'id\tv\n2\t{"k":[1,2]}\n1\t[true,null]\n')
    schema = json_file("s.json", flat_schema("json"))
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows == [["id", "v"], ["1", "[true,null]"], ["2", '{"k":[1,2]}']]


# Spec: "CSV/TSV: ... Empty cell → null"
def test_csv_empty_cell_for_nested_column_is_null(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,\n")
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1] == ["1", ""]


# Spec: "CSV/TSV: ... Invalid JSON → handled per --on-type-error" (AMBIGUITIES T49)
@pytest.mark.parametrize(
    "policy,expected", [("coerce-null", ""), ("keep-string", "{not json")]
)
def test_csv_invalid_json_cell_follows_the_policy(run_cli, csv_file, json_file, policy, expected):
    data = csv_file("a.csv", 'id,v\n1,"{not json"\n')
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", policy, data
    )
    assert result.rows[1] == ["1", expected]


# Spec: "CSV/TSV: ... Invalid JSON → handled per --on-type-error/error 5" (AMBIGUITIES T49)
def test_csv_invalid_json_cell_under_fail(run_cli, csv_file, json_file):
    data = csv_file("a.csv", 'id,v\n1,"{not json"\n')
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "fail", data
    )
    assert result.returncode in (4, 5), result.stderr


# Spec: "CSV/TSV ... single JSON literal" — a bare scalar is a literal but not a struct
def test_csv_scalar_literal_for_a_struct_column_fails_to_cast(run_cli, csv_file, json_file):
    data = csv_file("a.csv", "id,v\n1,5\n")
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "coerce-null", data
    )
    assert result.rows[1] == ["1", ""]


# Spec: "JSONL: Accept nested objects/arrays only when schema declares column as nested"
# AMBIGUITIES T57: JSONL text is not re-parsed as embedded JSON.
def test_jsonl_string_for_a_struct_column_is_a_cast_error(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": '{"a": 1}'}])
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "coerce-null", data
    )
    assert result.rows[1] == ["1", ""]


# Spec: "With --schema, Parquet/JSONL nesting must structurally match" (AMBIGUITIES T56)
def test_parquet_list_against_a_declared_struct(run_cli, parquet_file, json_file):
    table = pa.table(
        {"id": pa.array([1], pa.int64()), "v": pa.array([[1]], pa.list_(pa.int64()))}
    )
    data = parquet_file("a.parquet", table)
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema, "--on-type-error", "coerce-null", data
    )
    assert result.returncode in (0, 6), result.stderr


# Spec: mixed sources, as in the first example (events.jsonl plus users.parquet)
def test_jsonl_and_parquet_merge_onto_one_nested_schema(run_cli, jsonl_file, parquet_file, json_file):
    jsonl = jsonl_file("a.jsonl", [{"id": 2, "v": {"a": 2, "b": "j"}}])
    table = pa.table(
        {
            "id": pa.array([1], pa.int64()),
            "v": pa.array(
                [{"a": 1, "b": "p"}],
                pa.struct([pa.field("a", pa.int64()), pa.field("b", pa.string())]),
            ),
        }
    )
    parquet = parquet_file("b.parquet", table)
    schema = json_file("s.json", STRUCT_SCHEMA)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, jsonl, parquet)
    assert result.rows == [
        ["id", "v"],
        ["1", '{"a":1,"b":"p"}'],
        ["2", '{"a":2,"b":"j"}'],
    ]
