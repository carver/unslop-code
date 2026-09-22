"""Spec section: Schema with Nested Types — struct, array and map declarations."""

import json

from conftest import column, header_of, rows_of
from nested_helpers import INT, array, mapping, struct, write_schema


SPEC_EXAMPLE = [
    {"name": "id", "type": "int"},
    {
        "name": "user",
        "type": {
            "struct": {
                "fields": [
                    {"name": "name", "type": "string"},
                    {"name": "age", "type": "int"},
                    {
                        "name": "prefs",
                        "type": {"map": {"key": "string", "value": "string"}},
                    },
                ]
            }
        },
    },
    {
        "name": "items",
        "type": {
            "array": {
                "element": {
                    "struct": {
                        "fields": [
                            {"name": "sku", "type": "string"},
                            {"name": "qty", "type": "int"},
                        ]
                    }
                }
            }
        },
    },
]


# Phrase: "`--schema` JSON file shape" (the documented example)
# Context: Schema with Nested Types. The spec's own schema round-trips a record.
def test_spec_example_schema_is_accepted(jsonl_file, run_tool):
    write_schema(jsonl_file, SPEC_EXAMPLE)
    jsonl_file(
        "a.jsonl",
        [
            {
                "id": 1,
                "user": {"name": "ada", "age": 36, "prefs": {"tz": "UTC"}},
                "items": [{"sku": "x", "qty": 2}],
            }
        ],
    )
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "user", "items"]
    assert rows_of(result.stdout) == [
        [
            "1",
            '{"name":"ada","age":36,"prefs":{"tz":"UTC"}}',
            '[{"sku":"x","qty":2}]',
        ]
    ]


# Phrase: "struct: ordered list of named fields"
# Context: Supported nested kinds. Output order follows the declaration, not the input.
def test_struct_fields_keep_declared_order(jsonl_file, run_tool):
    write_schema(
        jsonl_file, [INT, {"name": "s", "type": struct(("z", "int"), ("a", "int"))}]
    )
    jsonl_file("a.jsonl", [{"id": 1, "s": {"a": 2, "z": 9}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "s") == ['{"z":9,"a":2}']


# Phrase: "struct: ordered list of named fields (names unique within struct)"
# Context: Supported nested kinds. A repeated field name is a bad schema (error 3).
def test_duplicate_struct_field_names_are_rejected(jsonl_file, run_tool):
    write_schema(
        jsonl_file, [INT, {"name": "s", "type": struct(("a", "int"), ("a", "string"))}]
    )
    jsonl_file("a.jsonl", [{"id": 1}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert result.stderr


# Phrase: "array<T>: homogeneous element type T (can be nested)"
# Context: Supported nested kinds. An array of arrays of structs is a legal type.
def test_arrays_nest(jsonl_file, run_tool):
    write_schema(
        jsonl_file, [INT, {"name": "grid", "type": array(array(struct(("q", "int"))))}]
    )
    jsonl_file("a.jsonl", [{"id": 1, "grid": [[{"q": 1}], [{"q": 2}, {"q": 3}]]}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "grid") == ['[[{"q":1}],[{"q":2},{"q":3}]]']


# Phrase: "map<string,T>: string keys only; value type T can be nested or primitive"
# Context: Supported nested kinds. A map of arrays is legal.
def test_map_values_may_be_nested(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "m", "type": mapping(array("int"))}])
    jsonl_file("a.jsonl", [{"id": 1, "m": {"b": [2], "a": [1, 3]}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "m") == ['{"a":[1,3],"b":[2]}']


# Phrase: "map<string,T>: string keys only"
# Context: Supported nested kinds. Ambiguity T51: a non-string key type is error 3.
def test_map_with_non_string_key_type_is_rejected(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "m", "type": mapping("string", key="int")}])
    jsonl_file("a.jsonl", [{"id": 1}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert result.stderr


# Phrase: "Primitive types unchanged: string, int, float, bool, date, timestamp"
# Context: Schema with Nested Types. Flat schemas keep behaving as before.
def test_primitive_columns_are_unchanged(csv_file, run_tool):
    write_schema(
        csv_file,
        [
            {"name": "s", "type": "string"},
            {"name": "i", "type": "int"},
            {"name": "f", "type": "float"},
            {"name": "b", "type": "bool"},
            {"name": "d", "type": "date"},
            {"name": "t", "type": "timestamp"},
        ],
    )
    csv_file("a.csv", "s,i,f,b,d,t\nx,1,1.5,true,2024-07-01,2024-07-01T05:00:00+02:00\n")
    result = run_tool(
        "--output", "-", "--key", "i", "--schema", "schema.json",
        "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [
        ["x", "1", "1.5", "true", "2024-07-01", "2024-07-01T03:00:00Z"]
    ]


# Phrase: "Supported nested kinds"
# Context: Schema with Nested Types. Ambiguity T50: the generic text spelling works too.
def test_nested_types_may_be_written_as_text(jsonl_file, run_tool):
    write_schema(
        jsonl_file,
        [INT, {"name": "m", "type": "map<string,array<int>>"}],
    )
    jsonl_file("a.jsonl", [{"id": 1, "m": {"a": ["1", 2]}}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "m") == ['{"a":[1,2]}']


# Phrase: "unknown types error deterministically"
# Context: Determinism Checklist. A type name that is neither primitive nor alias.
def test_unknown_nested_type_is_error_3(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "x", "type": {"tuple": {"fields": []}}}])
    jsonl_file("a.jsonl", [{"id": 1}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert result.stderr


# Phrase: "array<T>: homogeneous element type T"
# Context: Supported nested kinds. A malformed array declaration is a schema error.
def test_array_declaration_needs_an_element(jsonl_file, run_tool):
    write_schema(jsonl_file, [INT, {"name": "x", "type": {"array": {}}}])
    jsonl_file("a.jsonl", [{"id": 1}])
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.jsonl"
    )
    assert result.returncode == 3
    assert result.stderr


# Phrase: "Without --schema, nested inputs not allowed (error 6)"
# Context: Usage Additions. JSON Lines objects stay rejected without a schema.
def test_nested_jsonl_without_schema_is_error_6(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "user": {"name": "ada"}}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert result.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in result.stderr


# Phrase: "Error: ERR 6 nested structure requires provided --schema (exit 6)"
# Context: Schema Inference. A JSON array value is nesting too.
def test_nested_array_without_schema_is_error_6(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "tags": ["a"]}])
    result = run_tool("--output", "-", "--key", "id", "a.jsonl")
    assert result.returncode == 6
    assert "ERR 6 nested structure requires provided --schema" in result.stderr


# Phrase: "Inferred columns remain flat / CSV/TSV cells containing JSON treated as string"
# Context: Schema Inference (Unchanged, Flat-Only).
def test_csv_json_cells_stay_strings_without_schema(csv_file, run_tool):
    csv_file("a.csv", 'id,payload\n1,"{""a"": 1}"\n')
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.returncode == 0, result.stderr
    assert column(result.stdout, "payload") == ['{"a": 1}']
