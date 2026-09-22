"""Spec section: Nested Types Support -- schema shapes, casting, canonical JSON.

Each test names the spec phrase it pins down; see AMBIGUITIES.md for the
readings chosen where the prose allowed more than one.
"""
import json

from conftest import body, header

STRUCT_USER = {
    "struct": {
        "fields": [
            {"name": "name", "type": "string"},
            {"name": "age", "type": "int"},
        ]
    }
}


def schema_file(work, name, columns):
    return work.write(
        name, json.dumps({"columns": [{"name": n, "type": t} for n, t in columns]})
    )


# Phrase: "struct: ordered list of named fields"
# Context: Schema with Nested Types; JSONL supplies the object.
def test_struct_column_emits_json_object(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", STRUCT_USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {"name": "ada", "age": 36}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["id", "user"]
    assert body(r) == [["1", '{"name":"ada","age":36}']]


# Phrase: "Struct fields in schema-declared order"
# Context: Normalization & Output Encoding; input lists the keys backwards.
def test_struct_fields_follow_schema_order(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", STRUCT_USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {"age": 36, "name": "ada"}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"name":"ada","age":36}']]


# Phrase: "All struct fields included (even when null) with explicit `null` values"
# Context: Normalization & Output Encoding.
def test_struct_missing_fields_become_explicit_null(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", STRUCT_USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {}}, {"id": 2, "user": {"age": 7}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [
        ["1", '{"name":null,"age":null}'],
        ["2", '{"name":null,"age":7}'],
    ]


# Phrase: "If entire column value is null → emit CSV null literal"
# Context: Normalization & Output Encoding.
def test_entirely_null_nested_column_is_the_null_literal(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", STRUCT_USER)])
    work.jsonl("a.jsonl", [{"id": 1}, {"id": 2, "user": None}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", ""], ["2", ""]]


def test_null_nested_column_uses_configured_null_literal(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", STRUCT_USER)])
    work.jsonl("a.jsonl", [{"id": 1}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--csv-null-literal", "NULL", work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "NULL"]]


# Phrase: "array<T>: homogeneous element type T (can be nested)"
# Context: Schema with Nested Types.
def test_array_of_structs_preserves_element_order(run, work):
    items = {
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
    }
    schema_file(work, "s.json", [("id", "int"), ("items", items)])
    work.jsonl(
        "a.jsonl",
        [{"id": 1, "items": [{"sku": "z", "qty": 2}, {"sku": "a", "qty": 1}]}],
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '[{"sku":"z","qty":2},{"sku":"a","qty":1}]']]


# Phrase: "Arrays preserve original element order after casting"
# Context: Normalization & Output Encoding.
def test_array_of_primitives_keeps_order(run, work):
    schema_file(
        work, "s.json", [("id", "int"), ("xs", {"array": {"element": "int"}})]
    )
    work.jsonl("a.jsonl", [{"id": 1, "xs": [3, 1, 2]}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "[3,1,2]"]]


# Phrase: "map<string,T>: string keys only; value type T can be nested or primitive"
# Phrase: "Map keys sorted lexicographically"
# Context: Schema with Nested Types / Normalization & Output Encoding.
def test_map_keys_sorted_lexicographically(run, work):
    prefs = {"map": {"key": "string", "value": "string"}}
    schema_file(work, "s.json", [("id", "int"), ("prefs", prefs)])
    work.jsonl("a.jsonl", [{"id": 1, "prefs": {"b": "2", "A": "0", "a": "1"}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"A":"0","a":"1","b":"2"}']]


def test_map_of_arrays_nests(run, work):
    prefs = {"map": {"key": "string", "value": {"array": {"element": "int"}}}}
    schema_file(work, "s.json", [("id", "int"), ("m", prefs)])
    work.jsonl("a.jsonl", [{"id": 1, "m": {"b": [2, 1], "a": []}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"a":[],"b":[2,1]}']]


# Phrase: "struct ... prefs ... map" (a struct holding a map, from the spec's example)
# Context: Schema with Nested Types.
def test_struct_containing_map_field(run, work):
    user = {
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
    }
    schema_file(work, "s.json", [("id", "int"), ("user", user)])
    work.jsonl(
        "a.jsonl", [{"id": 1, "user": {"name": "ada", "age": 36, "prefs": {"t": "1"}}}]
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"name":"ada","age":36,"prefs":{"t":"1"}}']]


# Phrase: "Minified (no spaces)"
# Context: Normalization & Output Encoding.
def test_output_json_is_minified(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", STRUCT_USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {"name": "a b", "age": 1}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    cell = body(r)[0][1]
    assert cell == '{"name":"a b","age":1}'
    assert ", " not in cell and '": ' not in cell


# Phrase: "UTF-8, RFC 8259 JSON escaping"
# Context: Normalization & Output Encoding (see AMBIGUITIES T47).
def test_non_ascii_stays_utf8_and_quotes_are_escaped(run, work):
    schema_file(work, "s.json", [("id", "int"), ("user", STRUCT_USER)])
    work.jsonl("a.jsonl", [{"id": 1, "user": {"name": 'café "x"', "age": 1}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"name":"café \\"x\\"","age":1}']]


# Phrase: "Timestamps inside nested values normalized to UTC `Z`; `date` stays YYYY-MM-DD"
# Context: Normalization & Output Encoding.
def test_temporal_normalization_inside_nested(run, work):
    when = {
        "struct": {
            "fields": [
                {"name": "ts", "type": "timestamp"},
                {"name": "d", "type": "date"},
            ]
        }
    }
    schema_file(work, "s.json", [("id", "int"), ("w", when)])
    work.jsonl(
        "a.jsonl",
        [{"id": 1, "w": {"ts": "2024-01-02T03:04:05+02:00", "d": "2024-03-04"}}],
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"ts":"2024-01-02T01:04:05Z","d":"2024-03-04"}']]


# Phrase: "Primitive casting rules ... apply recursively inside nested values"
# Context: Casting & Validation; text from JSON becomes the declared primitive.
def test_primitive_casting_applies_inside_nested(run, work):
    row = {
        "struct": {
            "fields": [
                {"name": "n", "type": "int"},
                {"name": "f", "type": "float"},
                {"name": "b", "type": "bool"},
                {"name": "s", "type": "string"},
            ]
        }
    }
    schema_file(work, "s.json", [("id", "int"), ("v", row)])
    work.jsonl("a.jsonl", [{"id": 1, "v": {"n": "42", "f": "2.5", "b": 1, "s": 7}}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", '{"n":42,"f":2.5,"b":true,"s":"7"}']]


# Phrase: "null handling appl[ies] recursively inside nested values"
# Context: Casting & Validation; an explicit JSON null is not a cast failure.
def test_null_elements_inside_arrays_survive(run, work):
    schema_file(
        work, "s.json", [("id", "int"), ("xs", {"array": {"element": "int"}})]
    )
    work.jsonl("a.jsonl", [{"id": 1, "xs": [1, None, 3]}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "[1,null,3]"]]


# Phrase: "names unique within struct"
# Context: Schema with Nested Types; a duplicated field name is a schema error.
def test_duplicate_struct_field_names_exit_3(run, work):
    dup = {
        "struct": {
            "fields": [
                {"name": "a", "type": "int"},
                {"name": "a", "type": "string"},
            ]
        }
    }
    schema_file(work, "s.json", [("id", "int"), ("v", dup)])
    work.jsonl("a.jsonl", [{"id": 1}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3
    assert r.stdout == ""


# Phrase: "map<string,T>: string keys only"
# Context: Schema with Nested Types; a non-string key type is rejected.
def test_map_with_non_string_key_exits_3(run, work):
    schema_file(
        work, "s.json", [("id", "int"), ("m", {"map": {"key": "int", "value": "int"}})]
    )
    work.jsonl("a.jsonl", [{"id": 1}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3
    assert r.stdout == ""


# Phrase: "unknown types error deterministically"
# Context: Determinism Checklist.
def test_unknown_type_name_exits_3(run, work):
    schema_file(work, "s.json", [("id", "int"), ("v", "blob")])
    work.jsonl("a.jsonl", [{"id": 1}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.jsonl"),
    )
    assert r.returncode == 3
    assert r.stdout == ""


# Phrase: "Primitive types unchanged: string, int, float, bool, date, timestamp"
# Context: Schema with Nested Types; flat schemas keep working verbatim.
def test_flat_schema_unaffected(run, work):
    work.schema("s.json", [("id", "int"), ("name", "string")])
    work.csv("a.csv", ["id", "name"], [["2", "b"], ["1", "a"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "a"], ["2", "b"]]
