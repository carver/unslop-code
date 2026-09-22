"""Declaring nested types in `--schema`: struct, array<T> and map<string,T>."""

import pytest

# The schema document from the spec's "Schema with Nested Types" section.
SPEC_SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {
            "name": "user",
            "type": {
                "struct": {
                    "fields": [
                        {"name": "name", "type": "string"},
                        {"name": "age", "type": "int"},
                        {"name": "prefs", "type": {"map": {"key": "string", "value": "string"}}},
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
}

SPEC_ROW = {
    "id": 1,
    "user": {"name": "ada", "age": 36, "prefs": {"lang": "en"}},
    "items": [{"sku": "a1", "qty": 2}, {"sku": "b2", "qty": 5}],
}


# Spec: the "Schema with Nested Types" example document, end to end
def test_spec_schema_document_round_trips(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [SPEC_ROW])
    schema = json_file("s.json", SPEC_SCHEMA)
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows == [
        ["id", "user", "items"],
        [
            "1",
            '{"name":"ada","age":36,"prefs":{"lang":"en"}}',
            '[{"sku":"a1","qty":2},{"sku":"b2","qty":5}]',
        ],
    ]


# Spec: "struct: ordered list of named fields"
def test_struct_fields_keep_schema_order(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"c": 3, "a": 1, "b": 2}}])
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
                                {"name": "c", "type": "int"},
                                {"name": "a", "type": "int"},
                                {"name": "b", "type": "int"},
                            ]
                        }
                    },
                },
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"c":3,"a":1,"b":2}'


# Spec: "struct: ... (names unique within struct)"
def test_duplicate_struct_field_names_are_rejected(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
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
                                {"name": "a", "type": "int"},
                                {"name": "a", "type": "string"},
                            ]
                        }
                    },
                },
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.returncode != 0


# Spec: "array<T>: homogeneous element type T (can be nested)"
def test_array_of_arrays(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": [[1, 2], [], [3]]}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": {"array": {"element": {"array": {"element": "int"}}}}},
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == "[[1,2],[],[3]]"


# Spec: "map<string,T>: string keys only; value type T can be nested or primitive"
def test_map_of_structs(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"b": {"n": 2}, "a": {"n": 1}}}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {
                    "name": "v",
                    "type": {
                        "map": {
                            "key": "string",
                            "value": {"struct": {"fields": [{"name": "n", "type": "int"}]}},
                        }
                    },
                },
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"a":{"n":1},"b":{"n":2}}'


# Spec: "map<string,T>: string keys only"
def test_map_with_non_string_key_type_is_rejected(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"a": 1}}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "v", "type": {"map": {"key": "int", "value": "int"}}},
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.returncode != 0


# Spec: "array<T> ... (can be nested)" / "value type T can be nested"
def test_deeply_mixed_nesting(run_cli, jsonl_file, json_file):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {"k": [{"m": {"z": 1}}]}}])
    schema = json_file(
        "s.json",
        {
            "columns": [
                {"name": "id", "type": "int"},
                {
                    "name": "v",
                    "type": {
                        "map": {
                            "key": "string",
                            "value": {
                                "array": {
                                    "element": {
                                        "struct": {
                                            "fields": [
                                                {
                                                    "name": "m",
                                                    "type": {
                                                        "map": {"key": "string", "value": "int"}
                                                    },
                                                }
                                            ]
                                        }
                                    }
                                }
                            },
                        }
                    },
                },
            ]
        },
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.rows[1][1] == '{"k":[{"m":{"z":1}}]}'


# Spec: "struct" declared with no usable field list is malformed
@pytest.mark.parametrize("declaration", [{"array": {}}, {"map": {"key": "string"}}, {"union": {}}])
def test_malformed_nested_declarations_are_rejected(run_cli, jsonl_file, json_file, declaration):
    data = jsonl_file("a.jsonl", [{"id": 1, "v": {}}])
    schema = json_file(
        "s.json",
        {"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": declaration}]},
    )
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, data)
    assert result.returncode != 0
