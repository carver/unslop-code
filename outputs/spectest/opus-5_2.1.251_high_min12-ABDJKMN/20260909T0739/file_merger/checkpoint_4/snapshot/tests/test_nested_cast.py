"""Checkpoint 5: recursive casting and validation inside nested values."""
import re

from conftest import (array_of, cell, cells, map_of, merge, merge_paths,
                      nested_schema, struct_of, write_jsonl)


# --- Spec: "Nested values cast recursively to declared types" -------------
def test_leaves_are_cast_to_declared_types(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("u", struct_of(("a", "int"), ("f", "float"), ("b", "bool"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "u": {"a": "42", "f": "2.5", "b": "1"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"a":42,"f":2.5,"b":true}'


def test_casting_recurses_through_arrays_and_maps(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("m", map_of(array_of("int"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {"a": ["1", 2.0]}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "m") == '{"a":[1,2]}'


# --- Spec: "On cast failure within nested structures: coerce-null: set
#            field/element to JSON null" -----------------------------------
def test_coerce_null_nulls_only_the_failing_field(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("a", "int"), ("n", "string"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": "nope", "n": "ok"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "coerce-null")
    assert r.ok, r
    assert cell(r, 0, "u") == '{"a":null,"n":"ok"}'


def test_coerce_null_nulls_only_the_failing_array_element(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [1, "x", 3]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "coerce-null")
    assert r.ok, r
    assert cell(r, 0, "xs") == "[1,null,3]"


def test_coerce_null_nulls_only_the_failing_map_value(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("m", map_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {"a": 1, "b": "x"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "coerce-null")
    assert r.ok, r
    assert cell(r, 0, "m") == '{"a":1,"b":null}'


# --- Spec: "keep-string: set to original unparsed JSON string or
#            stringified form" ---------------------------------------------
def test_keep_string_keeps_the_leaf_as_text(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [1, "x"]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "keep-string")
    assert r.ok, r
    assert cell(r, 0, "xs") == '[1,"x"]'


def test_keep_string_stringifies_a_structure_in_a_primitive_slot(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [1, {"a": 1}]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "keep-string")
    assert r.ok, r
    assert cell(r, 0, "xs") == '[1,"{\\"a\\":1}"]'


# --- Spec: 'fail: emit ERR 4 cannot cast "<val>" to <type> in field
#            "<path>" (file=... line=...)' ---------------------------------
def test_fail_message_shape_for_a_nested_leaf(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("age", "int"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "u": {"age": 1}}, {"id": 2, "u": {"age": "old"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r
    assert r.stderr.startswith("ERR 4 "), r.stderr
    assert re.match(
        r'^ERR 4 cannot cast "old" to int in field "u\.age" '
        r'\(file=\S+ line=2\)\n$', r.stderr), r.stderr


def test_fail_path_uses_array_indices(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": [1, "x"]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r
    assert 'field "xs.1"' in r.stderr, r.stderr


def test_fail_path_uses_map_keys(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("m", map_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "m": {"country": "x"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r
    assert "country" in r.stderr, r.stderr


def test_fail_on_flat_column_uses_the_same_shape(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    files = {"a.csv": "id,v\n1,zz\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema),
              "--on-type-error", "fail")
    assert r.returncode == 4, r
    assert r.stderr.startswith('ERR 4 cannot cast "zz" to int in field "v" '), r.stderr


# --- Spec: "For json type: accept any JSON value without casting" ---------
def test_json_type_never_fails_to_cast(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "v": {"a": [1, "x", None, True]}},
        {"id": 2, "v": "plain"},
        {"id": 3, "v": 5},
    ])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.ok, r
    assert cells(r, "v") == ['{"a":[1,"x",null,true]}', '"plain"', "5"]


def test_json_type_does_not_normalize_timestamp_strings(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [("id", "int"), ("v", "json")])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "v": {"t": "2024-01-02T03:04:05+01:00"}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "v") == '{"t":"2024-01-02T03:04:05+01:00"}'


# --- Spec: "Primitive casting rules ... apply recursively inside nested
#            values" (temporal normalization) ------------------------------
def test_timestamps_inside_nested_normalize_to_utc(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("u", struct_of(("t", "timestamp"), ("d", "date"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [
        {"id": 1, "u": {"t": "2024-07-01T12:30:00+02:00", "d": "2024-07-01"}},
    ])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"t":"2024-07-01T10:30:00Z","d":"2024-07-01"}'


# --- Spec: "... null handling apply recursively inside nested values" -----
def test_json_null_leaf_stays_null(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": None}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.ok, r
    assert cell(r, 0, "u") == '{"a":null}'


def test_empty_string_leaf_is_null(tmp_path):
    # AMBIGUITIES T66: the null test applies recursively.
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "string")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": ""}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"a":null}'


# --- Spec: "All struct fields included (even when null)" ------------------
def test_missing_struct_field_becomes_explicit_null(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"), ("u", struct_of(("a", "int"), ("b", "int"))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": 1}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"a":1,"b":null}'


def test_undeclared_struct_key_is_dropped(tmp_path):
    # AMBIGUITIES T67
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": {"a": 1, "zz": 9}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert cell(r, 0, "u") == '{"a":1}'


# --- Spec: "cast failure within nested structures" - deep paths -----------
def test_deep_path_in_the_error_message(tmp_path):
    schema = nested_schema(tmp_path, "s.json", [
        ("id", "int"),
        ("items", array_of(struct_of(("qty", "int")))),
    ])
    src = write_jsonl(tmp_path, "a.jsonl",
                      [{"id": 1, "items": [{"qty": 1}, {"qty": "many"}]}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r
    assert 'field "items.1.qty"' in r.stderr, r.stderr


# --- Spec: "a struct where the whole value is not an object" --------------
def test_scalar_where_struct_expected_is_a_cast_failure(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("u", struct_of(("a", "int")))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "u": 5}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "coerce-null")
    assert r.ok, r
    assert cell(r, 0, "u") == ""


def test_object_where_array_expected_is_a_cast_failure(tmp_path):
    schema = nested_schema(tmp_path, "s.json",
                           [("id", "int"), ("xs", array_of("int"))])
    src = write_jsonl(tmp_path, "a.jsonl", [{"id": 1, "xs": {"a": 1}}])
    r = merge_paths([src], "--key", "id", "--schema", str(schema),
                    "--on-type-error", "fail")
    assert r.returncode == 4, r
