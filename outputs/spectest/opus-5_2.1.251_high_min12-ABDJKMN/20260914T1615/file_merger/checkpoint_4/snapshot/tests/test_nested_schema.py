"""Spec section: Nested Types Support — "Schema with Nested Types"."""

import json

from conftest import (array_t, body, col, header, json_cells, map_t, run,
                      run_ok, struct_t, write, write_json, write_jsonl,
                      write_nested_schema, write_schema)

SPEC_EXAMPLE = {
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


# --- Spec: "`--schema` JSON file shape: {"columns": [...]}" (the worked
#           example with struct, map and array-of-struct) ---
# Context: Schema with Nested Types; the document must be accepted verbatim.
def test_spec_example_schema_is_accepted(ws):
    s = write_json(ws / "s.json", SPEC_EXAMPLE)
    a = write_jsonl(ws / "a.jsonl", [{
        "id": 1,
        "user": {"name": "ann", "age": 30, "prefs": {"tz": "UTC"}},
        "items": [{"sku": "x", "qty": 2}],
    }])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert header(res.stdout) == ["id", "user", "items"]
    assert json_cells(res.stdout, "user") == [
        {"name": "ann", "age": 30, "prefs": {"tz": "UTC"}}]
    assert json_cells(res.stdout, "items") == [[{"sku": "x", "qty": 2}]]


# --- Spec: "**struct**: ordered list of named fields" ---
# Context: Schema with Nested Types; declaration order is the output order.
def test_struct_fields_keep_declared_order(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("u", struct_t(("z", "int"), ("a", "int"), ("m", "int"))),
    ])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1, "m": 2, "z": 3}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "u") == ['{"z":3,"a":1,"m":2}']


# --- Spec: "**struct**: ... (names unique within struct)" ---
# Context: Schema with Nested Types; a duplicated field name is a schema error.
def test_duplicate_struct_field_name_is_a_schema_error(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("u", struct_t(("a", "int"), ("a", "string"))),
    ])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run("--output", "-", "--key", "id", "--schema", s, a)
    assert res.returncode == 3
    assert res.stderr != ""


# --- Spec: "**array<T>**: homogeneous element type T (can be nested)" ---
# Context: Schema with Nested Types; array of array of int.
def test_array_of_array_of_primitive(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("grid", array_t(array_t("int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "grid": [[1, 2], [3]]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "grid") == ["[[1,2],[3]]"]


# --- Spec: "**array<T>**: homogeneous element type T" ---
# Context: Schema with Nested Types; every element casts to the same T.
def test_array_elements_are_cast_to_the_declared_element_type(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("float"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [1, "2.5", 3]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "xs") == ["[1.0,2.5,3.0]"]


# --- Spec: "**map<string,T>**: string keys only; value type T can be nested
#           or primitive" ---
# Context: Schema with Nested Types; map of struct values.
def test_map_with_nested_value_type(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"),
        ("m", map_t(struct_t(("n", "int")))),
    ])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "m": {"b": {"n": 1},
                                                     "a": {"n": 2}}}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "m") == ['{"a":{"n":2},"b":{"n":1}}']


# --- Spec: "map<string,T>: string keys only" ---
# Context: Schema with Nested Types; a non-string declared key type is rejected.
def test_map_with_non_string_key_type_is_rejected(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("m", map_t("int", key="int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "m": {"1": 2}}])
    res = run("--output", "-", "--key", "id", "--schema", s, a)
    assert res.returncode == 3


# --- Spec: "Primitive types unchanged: `string`, `int`, `float`, `bool`,
#           `date`, `timestamp`" ---
# Context: Schema with Nested Types; flat schemas behave as before.
def test_primitive_columns_unchanged(ws):
    s = write_schema(ws / "s.json", [("id", "int"), ("when", "timestamp"),
                                     ("d", "date"), ("f", "float"),
                                     ("b", "bool"), ("s", "string")])
    a = write(ws / "a.csv",
              "id,when,d,f,b,s\n1,2024-01-02T03:04:05+02:00,2024-05-06,1,true,x\n")
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert body(res.stdout) == ["1,2024-01-02T01:04:05Z,2024-05-06,1.0,true,x"]


# --- Spec: "struct" / "array" / "map" nesting inside one another ---
# Context: Schema with Nested Types; "can be nested" applies at every level.
def test_deeply_nested_declaration(ws):
    inner = struct_t(("tags", array_t("string")), ("meta", map_t("int")))
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("box", array_t(inner))])
    a = write_jsonl(ws / "a.jsonl", [
        {"id": 1, "box": [{"tags": ["a", "b"], "meta": {"k": 1}}]}])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert col(res.stdout, "box") == ['[{"tags":["a","b"],"meta":{"k":1}}]']


# --- Spec: an unknown type name "errors deterministically" ---
# Context: Determinism Checklist; a bogus type inside a nested declaration.
def test_unknown_nested_element_type_is_an_error(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("xs", array_t("wat"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [1]}])
    res = run("--output", "-", "--key", "id", "--schema", s, a)
    assert res.returncode == 3
    assert res.stderr != ""


# --- Spec: "Referencing non-primitive (struct/array/map) in keys/partitions
#           is error 3" ---
# Context: Usage Additions; the whole column is a struct.
def test_key_on_whole_struct_column_is_error_3(ws):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run("--output", "-", "--key", "u", "--schema", s, a)
    assert res.returncode == 3
    assert "ERR 3" in res.stderr


# --- Spec: "Paths must resolve to primitive types" ---
# Context: Usage Additions; array and map columns as keys are equally invalid.
def test_key_on_whole_array_or_map_column_is_error_3(ws):
    s = write_nested_schema(ws / "s.json", [
        ("id", "int"), ("xs", array_t("int")), ("m", map_t("int"))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "xs": [1], "m": {"a": 1}}])
    for key in ("xs", "m"):
        res = run("--output", "-", "--key", key, "--schema", s, a)
        assert res.returncode == 3, key
        assert "ERR 3" in res.stderr


# --- Spec: "Referencing non-primitive ... in keys/partitions is error 3" ---
# Context: Usage Additions; the partition side of the same rule.
def test_partition_on_nested_column_is_error_3(ws, tmp_path):
    s = write_nested_schema(ws / "s.json", [("id", "int"),
                                            ("u", struct_t(("a", "int")))])
    a = write_jsonl(ws / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run("--output", str(ws / "out"), "--key", "id",
              "--partition-by", "u", "--schema", s, a)
    assert res.returncode == 3
    assert "ERR 3" in res.stderr
