"""Checkpoint 5: normalization and canonical-JSON output encoding."""
import json

from conftest import (array_of, cell, cells, map_of, merge, merge_paths,
                      nested_schema, struct_of, write_jsonl)


# --- Spec: "If entire column value is null -> emit CSV null literal" ------
def test_null_column_uses_the_csv_null_literal(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": None}, {"id": 2}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "u") == ["", ""]


def test_null_column_uses_a_custom_null_literal(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": None}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--csv-null-literal", "\\N")
    assert r.ok, r
    assert cell(r, 0, "u") == "\\N"


def test_a_struct_of_all_nulls_is_not_a_null_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"a":null}'


def test_an_empty_array_is_not_a_null_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": []}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[]"


def test_an_empty_map_is_not_a_null_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("m", map_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "m") == "{}"


def test_json_null_value_is_a_null_column(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": None}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "v") == ""


# --- Spec: "Minified (no spaces)" ----------------------------------------
def test_output_json_is_minified(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "v": {"a": [1, 2], "b": {}}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert " " not in cell(r, 0, "v")
    assert cell(r, 0, "v") == '{"a":[1,2],"b":{}}'


# --- Spec: "UTF-8, RFC 8259 JSON escaping" -------------------------------
def test_control_characters_and_quotes_are_escaped(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("s", "string")))])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "u": {"s": 'a"b\\c\nd\te\x01'}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    body = cell(r, 0, "u")
    assert body == '{"s":"a\\"b\\\\c\\nd\\te\\u0001"}'
    assert json.loads(body) == {"s": 'a"b\\c\nd\te\x01'}


def test_non_ascii_is_emitted_as_utf8(tmp_path):
    # AMBIGUITIES T58: literal UTF-8, not \uXXXX escapes.
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("s", "string")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"s": "héllo ☃"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"s":"héllo ☃"}'


# --- Spec: "Struct fields in schema-declared order" -----------------------
def test_struct_order_is_independent_of_input_order(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("b", "int"), ("a", "int"), ("c", "int"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "u": {"a": 1, "b": 2, "c": 3}},
        {"id": 2, "u": {"c": 3, "b": 2, "a": 1}},
    ])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cells(r, "u") == ['{"b":2,"a":1,"c":3}'] * 2


# --- Spec: "Map keys sorted lexicographically" ---------------------------
def test_map_keys_are_sorted(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("m", map_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "m": {"b": 2, "B": 4, "a": 1, "10": 0}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "m") == '{"10":0,"B":4,"a":1,"b":2}'


def test_nested_map_keys_are_sorted_recursively(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("m", map_of(map_of("int")))])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "m": {"z": {"y": 1, "x": 2}}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "m") == '{"z":{"x":2,"y":1}}'


# --- Spec: "Arrays preserve original element order after casting" --------
def test_array_order_is_preserved(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [5, 1, 4, 1, 3]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[5,1,4,1,3]"


# --- Spec: "Timestamps inside nested values normalized to UTC Z; date stays
#            YYYY-MM-DD" --------------------------------------------------
def test_temporal_normalization_inside_arrays(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("ts", array_of("timestamp")), ("ds", array_of("date")),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{
        "id": 1,
        "ts": ["2024-02-03T01:02:03Z", "2024-02-03 04:05:06-03:00"],
        "ds": ["2024-02-03"],
    }])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "ts") == '["2024-02-03T01:02:03Z","2024-02-03T07:05:06Z"]'
    assert cell(r, 0, "ds") == '["2024-02-03"]'


# --- Spec: "All struct fields included (even when null) with explicit null" -
def test_all_declared_fields_present_even_when_absent_in_input(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("u", struct_of(("a", "int"), ("b", "string"), ("c", array_of("int")))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"b": "x"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"a":null,"b":"x","c":null}'


# --- Spec: "This JSON is the CSV cell content for nested columns" --------
def test_json_cell_is_csv_quoted(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "string")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": "x,y"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.stdout == 'id,u\n1,"{""a"":""x,y""}"\n'


# --- Spec: "canonical JSON": floats and ints keep JSON number syntax -----
def test_numbers_are_plain_json_numbers(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("i", "int"), ("f", "float"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"i": -3, "f": 1.0}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"i":-3,"f":1.0}'


def test_bools_are_json_true_false(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("bool"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [True, False, 1, 0]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "xs") == "[true,false,true,false]"


# --- Spec: "Nested casting/normalization yields canonical JSON per ordering
#            rules" (same logical value from two formats -> same cell) ----
def test_same_value_from_csv_and_jsonl_produce_identical_cells(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("a", "int"), ("m", map_of("string")))),
    ])
    j = write_jsonl(tmp_path, "a.jsonl",
                    [{"id": 1, "u": {"m": {"b": "2", "a": "1"}, "a": 5}}])
    files = {"b.csv": 'id,u\n2,"{""u"": 1, ""a"":5, ""m"":{""a"":""1"",""b"":""2""}}"\n'}
    from conftest import write as _write
    c = _write(tmp_path, "b.csv", files["b.csv"])
    r = merge_paths([j, c], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert len(set(cells(r, "u"))) == 1
