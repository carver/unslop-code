"""Checkpoint 5: the `--schema` document with nested types."""
import json

from conftest import (array_of, cell, map_of, merge, merge_paths, nested_schema,
                      struct_of, write, write_jsonl)


# --- Spec: "--schema JSON file shape" (the document from the spec verbatim) --
SPEC_SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {"name": "user", "type": {
            "struct": {
                "fields": [
                    {"name": "name", "type": "string"},
                    {"name": "age", "type": "int"},
                    {"name": "prefs", "type": {"map": {"key": "string",
                                                       "value": "string"}}},
                ]
            }
        }},
        {"name": "items", "type": {"array": {"element": {
            "struct": {"fields": [
                {"name": "sku", "type": "string"},
                {"name": "qty", "type": "int"},
            ]}}
        }}},
    ]
}


def test_spec_schema_document_is_accepted(tmp_path):
    schema = write(tmp_path, "s.json", json.dumps(SPEC_SCHEMA))
    src = write_jsonl(tmp_path, "a.jsonl", [{
        "id": 1,
        "user": {"name": "ann", "age": 30, "prefs": {"b": "2", "a": "1"}},
        "items": [{"sku": "x", "qty": 2}],
    }])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[0] == ["id", "user", "items"]
    assert cell(r, 0, "user") == '{"name":"ann","age":30,"prefs":{"a":"1","b":"2"}}'
    assert cell(r, 0, "items") == '[{"sku":"x","qty":2}]'


# --- Spec: "struct: ordered list of named fields" -------------------------
def test_struct_fields_keep_declared_order(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("u", struct_of(("z", "string"), ("a", "string"), ("m", "string"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "u": {"a": "A", "m": "M", "z": "Z"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"z":"Z","a":"A","m":"M"}'


# --- Spec: "struct: ... (names unique within struct)" ---------------------
def test_duplicate_struct_field_names_are_rejected(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("u", struct_of(("a", "int"), ("a", "string"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.returncode == 3, r
    assert r.stderr.strip()


# --- Spec: "array<T>: homogeneous element type T (can be nested)" ---------
def test_array_of_primitives(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [3, 1, 2]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[3,1,2]"


def test_array_of_array_of_struct(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("g", array_of(array_of(struct_of(("k", "string"), ("v", "int"))))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "g": [[{"k": "a", "v": 1}], []]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "g") == '[[{"k":"a","v":1}],[]]'


# --- Spec: "map<string,T>: string keys only; value type T can be nested" --
def test_map_of_nested_value(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("m", map_of(array_of("int"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {"b": [2], "a": [1]}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "m") == '{"a":[1],"b":[2]}'


def test_map_with_non_string_key_type_is_rejected(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("m", map_of("string", key="int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {"a": "b"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.returncode == 3, r


# --- Spec: "Primitive types unchanged: string, int, float, bool, date,
#            timestamp" --------------------------------------------------
def test_primitive_columns_still_work_alongside_nested(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("f", "float"), ("b", "bool"),
        ("d", "date"), ("t", "timestamp"), ("s", "string"),
        ("n", struct_of(("x", "int"))),
    ])
    files = {"a.csv": "id,f,b,d,t,s,n\n1,2.5,true,2024-01-02,"
                      "2024-01-02T03:04:05+01:00,hi,\"{\"\"x\"\":7}\"\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", "2.5", "true", "2024-01-02",
                           "2024-01-02T02:04:05Z", "hi", '{"x":7}']


# --- Spec: "array<T>" and "map<string,T>" written as type *strings* -------
def test_generic_type_strings_are_accepted(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("xs", "array<int>"), ("m", "map<string,int>"),
    ])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "xs": [1, 2], "m": {"b": 2, "a": 1}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[1,2]"
    assert cell(r, 0, "m") == '{"a":1,"b":2}'


def test_nested_generic_type_strings(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("m", "map<string,array<float>>"),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {"a": [1, 2.5]}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "m") == '{"a":[1.0,2.5]}'


# --- Spec: "unknown types error deterministically" ------------------------
def test_unknown_type_name_is_a_schema_error(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("x", "widget")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "x": 1}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.returncode == 3, r


def test_bare_array_without_element_type_is_rejected(tmp_path):
    # AMBIGUITIES T62: the element/value parameter is mandatory.
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("x", "array")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "x": [1]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.returncode == 3, r
