"""Spec section: Schema with Nested Types (checkpoint 4)."""
import json

from conftest import (array_t, cell, col, map_t, run_tool, struct_t,
                      write_csv, write_file, write_json, write_jsonl,
                      write_nested_schema)


# --------------------------------------------------------------------------
# Phrase: the documented `--schema` JSON file shape
# Context: the exact document printed in the spec must be accepted verbatim.
# --------------------------------------------------------------------------
SPEC_SCHEMA = {
    "columns": [
        {"name": "id", "type": "int"},
        {"name": "user", "type": {
            "struct": {
                "fields": [
                    {"name": "name", "type": "string"},
                    {"name": "age", "type": "int"},
                    {"name": "prefs", "type": {"map": {"key": "string",
                                                       "value": "string"}}}
                ]
            }
        }},
        {"name": "items", "type": {"array": {"element": {
            "struct": {"fields": [
                {"name": "sku", "type": "string"},
                {"name": "qty", "type": "int"}
            ]}}
        }}}
    ]
}


def test_spec_schema_document_is_accepted(tmp_path):
    schema = write_json(tmp_path / "s.json", SPEC_SCHEMA)
    src = write_jsonl(tmp_path / "a.jsonl", [
        {"id": 1,
         "user": {"name": "ada", "age": 36, "prefs": {"tz": "UTC"}},
         "items": [{"sku": "x", "qty": 2}]},
    ])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    rows = res.rows()
    assert rows[0] == ["id", "user", "items"]
    assert cell(rows, "user") == \
        '{"name":"ada","age":36,"prefs":{"tz":"UTC"}}'
    assert cell(rows, "items") == '[{"sku":"x","qty":2}]'


# --------------------------------------------------------------------------
# Phrase: "struct: ordered list of named fields"
# Context: Supported nested kinds.
# --------------------------------------------------------------------------
def test_struct_declaration_round_trips(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("u", struct_t(("a", "int"), ("b", "bool"))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "u": {"a": 5, "b": True}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "u") == '{"a":5,"b":true}'


# Phrase: "struct: ... (names unique within struct)"
# Context: duplicate field names make the schema invalid (error 3).
def test_duplicate_struct_field_names_rejected(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("u", struct_t(("a", "int"), ("a", "int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 3
    assert res.stderr.strip() != ""


# --------------------------------------------------------------------------
# Phrase: "array<T>: homogeneous element type T (can be nested)"
# Context: Supported nested kinds.
# --------------------------------------------------------------------------
def test_array_of_primitives(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("t", array_t("string")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "t": ["x", "y"]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "t") == '["x","y"]'


def test_array_of_arrays(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("m", array_t(array_t("int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": [[1, 2], [3]]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '[[1,2],[3]]'


def test_array_of_maps_of_structs(tmp_path):
    inner = struct_t(("q", "int"))
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("m", array_t(map_t(inner))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "m": [{"k": {"q": 7}}]}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '[{"k":{"q":7}}]'


# --------------------------------------------------------------------------
# Phrase: "map<string,T>: string keys only; value type T can be nested or
#          primitive"
# Context: Supported nested kinds.
# --------------------------------------------------------------------------
def test_map_of_primitive_values(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("m", map_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"a": 1}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '{"a":1}'


def test_map_of_nested_values(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"),
                                 ("m", map_t(array_t("int"))))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"a": [1, 2]}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert cell(res.rows(), "m") == '{"a":[1,2]}'


# Phrase: "map<string,T>: string keys only"
# Context: a non-string declared key type is a schema error (T68).
def test_non_string_map_key_rejected(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("id", "int"), ("m", map_t("int", key="int")))
    src = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "m": {"1": 2}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 3


# --------------------------------------------------------------------------
# Phrase: "Primitive types unchanged: string, int, float, bool, date,
#          timestamp"
# Context: primitives keep working beside nested columns.
# --------------------------------------------------------------------------
def test_primitives_beside_nested_columns(tmp_path):
    schema = write_nested_schema(
        tmp_path / "s.json",
        ("id", "int"), ("f", "float"), ("b", "bool"), ("d", "date"),
        ("ts", "timestamp"), ("s", "string"), ("n", array_t("int")))
    src = write_jsonl(tmp_path / "a.jsonl", [
        {"id": 1, "f": 1.5, "b": True, "d": "2024-01-02",
         "ts": "2024-01-02T03:04:05Z", "s": "x", "n": [1]},
    ])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    rows = res.rows()
    assert rows[1] == ["1", "1.5", "true", "2024-01-02",
                       "2024-01-02T03:04:05Z", "x", "[1]"]


# --------------------------------------------------------------------------
# Phrase: "Schema with Nested Types" — malformed declarations
# Context: an unknown nested kind or a missing member is a schema error.
# --------------------------------------------------------------------------
def test_unknown_nested_kind_rejected(tmp_path):
    schema = write_json(tmp_path / "s.json",
                        {"columns": [{"name": "a", "type": {"tuple": {}}}]})
    src = write_csv(tmp_path / "a.csv", ["a", "1"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 3


def test_array_without_element_rejected(tmp_path):
    schema = write_json(tmp_path / "s.json",
                        {"columns": [{"name": "a", "type": {"array": {}}}]})
    src = write_csv(tmp_path / "a.csv", ["a", "[]"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 3


def test_struct_without_fields_rejected(tmp_path):
    schema = write_json(
        tmp_path / "s.json",
        {"columns": [{"name": "a", "type": {"struct": {"fields": "x"}}}]})
    src = write_csv(tmp_path / "a.csv", ["a", "{}"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 3


def test_unknown_primitive_inside_nested_rejected(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("a", array_t("widget")))
    src = write_csv(tmp_path / "a.csv", ["a", "[]"])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 3


# --------------------------------------------------------------------------
# Phrase: "Output remains CSV with nested columns as canonical JSON"
# Context: the header still carries the declared column names in order.
# --------------------------------------------------------------------------
def test_header_and_column_order_follow_the_schema(tmp_path):
    schema = write_nested_schema(tmp_path / "s.json",
                                 ("z", array_t("int")), ("id", "int"),
                                 ("a", struct_t(("k", "string"))))
    src = write_jsonl(tmp_path / "a.jsonl",
                      [{"id": 1, "z": [1], "a": {"k": "v"}}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["z", "id", "a"]
